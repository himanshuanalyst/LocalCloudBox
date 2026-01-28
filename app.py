import os
import datetime
import zipfile
import io
import pandas as pd
from flask import Flask, render_template, request, send_from_directory, redirect, url_for, session, send_file, flash, jsonify

app = Flask(__name__)
app.secret_key = "secret_key_secure_123"

# --- CONFIGURATION ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_FOLDER = os.path.join(BASE_DIR, 'My_Documents')
USERNAME = "admin"
PASSWORD = "password123"

if not os.path.exists(ROOT_FOLDER):
    os.makedirs(ROOT_FOLDER)

# --- LOGIN CHECK ---
def check_auth():
    return session.get('logged_in')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == USERNAME and request.form['password'] == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            flash("Invalid Credentials!", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- MAIN ROUTES ---
@app.route('/', defaults={'subpath': ''})
@app.route('/browse/', defaults={'subpath': ''})
@app.route('/browse/<path:subpath>')
def index(subpath):
    if not check_auth(): return redirect(url_for('login'))
    
    abs_path = os.path.join(ROOT_FOLDER, subpath)
    
    if not os.path.commonprefix([abs_path, ROOT_FOLDER]) == ROOT_FOLDER:
        return "Access Denied", 403

    if os.path.isfile(abs_path):
        return redirect(url_for('index', subpath=os.path.dirname(subpath)))

    # --- GROUP BY LOGIC ADDED HERE ---
    group_by = request.args.get('group_by')
    sort_by = request.args.get('sort', 'name')
    order = request.args.get('order', 'asc')

    # Agar Group By active hai, to Sort By Type force karein
    if group_by == 'type':
        sort_by = 'type'
        order = 'asc'

    items = []
    try:
        with os.scandir(abs_path) as entries:
            for entry in entries:
                stats = entry.stat()
                size = stats.st_size
                # Type detection logic
                if entry.is_dir():
                    f_type = 'Folder'
                else:
                    ext = entry.name.split('.')[-1].lower() if '.' in entry.name else 'File'
                    f_type = ext.upper()

                items.append({
                    'name': entry.name,
                    'path': os.path.relpath(entry.path, ROOT_FOLDER).replace('\\', '/'),
                    'is_dir': entry.is_dir(),
                    'size_raw': size,
                    'size': f"{size/1024:.1f} KB" if not entry.is_dir() else "-",
                    'mtime_raw': stats.st_mtime,
                    'date': datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M'),
                    'type': f_type # Simplified type for grouping
                })
    except Exception as e:
        flash(str(e), "danger")

    reverse = True if order == 'desc' else False
    
    # Sorting Logic
    if sort_by == 'date':
        items.sort(key=lambda x: x['mtime_raw'], reverse=reverse)
    elif sort_by == 'size':
        items.sort(key=lambda x: x['size_raw'], reverse=reverse)
    elif sort_by == 'type':
        # Type ke hisab se sort, folder hamesha upar
        items.sort(key=lambda x: (not x['is_dir'], x['type'], x['name']), reverse=reverse)
    else:
        items.sort(key=lambda x: x['name'].lower(), reverse=reverse)

    breadcrumbs = [{'name': 'Home', 'path': ''}]
    parts = subpath.split('/') if subpath else []
    current_path = ""
    for part in parts:
        if part:
            current_path = os.path.join(current_path, part).replace('\\', '/')
            breadcrumbs.append({'name': part, 'path': current_path})

    return render_template('index.html', items=items, current_path=subpath, breadcrumbs=breadcrumbs, sort_by=sort_by, order=order, group_by=group_by)

# --- ACTIONS ---

# [NEW] Rename Route
@app.route('/rename', methods=['POST'])
def rename_item():
    if not check_auth(): return redirect(url_for('login'))
    
    current_path = request.form.get('current_path', '')
    old_name = request.form.get('old_name')
    new_name = request.form.get('new_name')
    
    if old_name and new_name:
        dir_path = os.path.join(ROOT_FOLDER, current_path)
        old_path = os.path.join(dir_path, old_name)
        new_path = os.path.join(dir_path, new_name)
        
        try:
            if os.path.exists(new_path):
                flash("A file/folder with that name already exists!", "warning")
            else:
                os.rename(old_path, new_path)
                flash("Renamed successfully", "success")
        except Exception as e:
            flash(f"Error renaming: {str(e)}", "danger")
            
    return redirect(url_for('index', subpath=current_path))

@app.route('/upload', methods=['POST'])
def upload():
    if not check_auth(): return redirect(url_for('login'))
    path = request.form.get('current_path', '')
    target = os.path.join(ROOT_FOLDER, path)
    for file in request.files.getlist('files'):
        if file.filename:
            file.save(os.path.join(target, file.filename))
    flash("Upload Successful", "success")
    return redirect(url_for('index', subpath=path))

@app.route('/create_folder', methods=['POST'])
def create_folder():
    if not check_auth(): return redirect(url_for('login'))
    path = request.form.get('current_path', '')
    name = request.form.get('folder_name')
    if name:
        os.makedirs(os.path.join(ROOT_FOLDER, path, name), exist_ok=True)
    return redirect(url_for('index', subpath=path))

@app.route('/bulk_action', methods=['POST'])
def bulk_action():
    if not check_auth(): return redirect(url_for('login'))
    action = request.form.get('action')
    selected_files = request.form.getlist('selected_files')
    current_path = request.form.get('current_path', '')
    abs_base = os.path.join(ROOT_FOLDER, current_path)

    if not selected_files:
        flash("No files selected", "warning")
        return redirect(url_for('index', subpath=current_path))

    if action == 'delete':
        for item in selected_files:
            p = os.path.join(abs_base, item)
            if os.path.exists(p):
                if os.path.isdir(p):
                    import shutil
                    shutil.rmtree(p)
                else:
                    os.remove(p)
        flash(f"Deleted {len(selected_files)} items", "success")
        return redirect(url_for('index', subpath=current_path))

    elif action == 'download':
        if len(selected_files) == 1 and not os.path.isdir(os.path.join(abs_base, selected_files[0])):
            return send_from_directory(abs_base, selected_files[0], as_attachment=True)
        
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w') as zf:
            for item in selected_files:
                p = os.path.join(abs_base, item)
                if os.path.isfile(p):
                    zf.write(p, item)
        memory_file.seek(0)
        return send_file(memory_file, download_name='files.zip', as_attachment=True)

    return redirect(url_for('index', subpath=current_path))

@app.route('/view_file')
def view_file():
    if not check_auth(): return jsonify({'error': 'Auth required'})
    path = request.args.get('path')
    abs_path = os.path.join(ROOT_FOLDER, path)
    
    ext = path.split('.')[-1].lower()
    content = ""
    file_type = "unknown"

    try:
        if ext in ['txt', 'py', 'js', 'html', 'css', 'json', 'md']:
            file_type = "text"
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(5000)
        elif ext in ['csv']:
            file_type = "table"
            df = pd.read_csv(abs_path, nrows=50)
            content = df.to_html(classes='table table-striped table-sm', index=False)
        elif ext in ['xlsx', 'xls']:
            file_type = "table"
            df = pd.read_excel(abs_path, nrows=50)
            content = df.to_html(classes='table table-striped table-sm', index=False)
        elif ext == 'pdf':
            file_type = "pdf"
        elif ext in ['jpg', 'jpeg', 'png', 'gif']:
            file_type = "image"
    except Exception as e:
        content = f"Error: {str(e)}"

    return render_template('view_modal.html', content=content, file_type=file_type, path=path, name=os.path.basename(path))

@app.route('/raw/<path:filepath>')
def raw_file(filepath):
    directory = os.path.join(ROOT_FOLDER, os.path.dirname(filepath))
    return send_from_directory(directory, os.path.basename(filepath))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)