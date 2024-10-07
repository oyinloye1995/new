from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# This will hold user data in memory (for demonstration purposes)
users = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/api/register', methods=['POST'])
def register_user():
    data = request.json
    users.append(data)  # Store user data in the list
    return jsonify(message="User registered successfully!", data=data)

@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.json
    user = next((u for u in users if u['Email'] == data['username'] and u['Password'] == data['password']), None)
    if user:
        return jsonify(message="Login successful!")
    return jsonify(message="Invalid credentials!"), 401

@app.route('/api/users', methods=['GET'])
def get_users():
    return jsonify(users)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)  
