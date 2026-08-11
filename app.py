from flask import Flask, render_template, request, jsonify

app = Flask(__name__, template_folder='.', static_folder='.')

users = []


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


@app.route('/users')
def users_page():
    return render_template('getusers.html')


@app.route('/getusers.html')
def users_html():
    return render_template('getusers.html')


@app.route('/index.html')
def index_html():
    return render_template('index.html')


@app.route('/api/register', methods=['POST'])
def register_user():
    data = request.get_json(silent=True)

    if data is None:
        data = request.form.to_dict()

    if not data:
        return jsonify({'error': 'No form data received'}), 400

    required_fields = ['FullName', 'Email', 'Password', 'City', 'State']
    missing = [field for field in required_fields if not str(data.get(field, '')).strip()]
    if missing:
        return jsonify({'error': f'Missing required fields: {missing}'}), 400

    email = str(data.get('Email', '')).strip().lower()
    if any(str(user.get('Email', '')).strip().lower() == email for user in users):
        return jsonify({'error': 'User already exists with this email'}), 409

    sanitized_user = {key: value for key, value in data.items()}
    users.append(sanitized_user)
    return jsonify({'message': 'User registered successfully!', 'data': sanitized_user})


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


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)

