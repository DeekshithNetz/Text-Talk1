from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from flask_socketio import SocketIO, emit, join_room
from datetime import datetime
from flask_cors import CORS


app = Flask(__name__)
CORS(app, supports_credentials=True)  # <- allow cross-origin requests with cookies/session
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

app.config['SECRET_KEY'] = 'mysecret'

# Neon PostgreSQL connection
app.config['SQLALCHEMY_DATABASE_URI'] = (
    "postgresql://neondb_owner:npg_Ssjl0dDwk9Zo@ep-falling-dream-atv775dp-pooler.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)



login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({
        "success": False,
        "message": "Login required"
    }), 401

# ===== Database Models =====
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(100), nullable=False)
    receiver = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== API Endpoints for Decoupled Frontend =====

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password required"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"success": False, "message": "Username already exists"}), 400

    new_user = User(username=username, password=password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"success": True, "message": "User registered successfully"}), 200


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password required"}), 400

    user = User.query.filter_by(username=username, password=password).first()
    if user:
        login_user(user)
        session["username"] = username
        return jsonify({"success": True, "message": "Login successful"}), 200

    return jsonify({"success": False, "message": "Invalid credentials"}), 401


@app.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    logout_user()
    return jsonify({"success": True, "message": "Logged out successfully"}), 200


@app.route("/api/users")
@login_required
def api_users():
    users = User.query.filter(User.id != current_user.id).all()
    user_list = [{"username": u.username} for u in users]
    print(user_list)
    return jsonify({"success": True, "users": user_list}), 200


@app.route("/api/messages/<receiver>")
@login_required
def api_messages(receiver):
    sender = current_user.username
    messages = Message.query.filter(
        ((Message.sender == sender) & (Message.receiver == receiver)) |
        ((Message.sender == receiver) & (Message.receiver == sender))
    ).order_by(Message.timestamp).all()

    msg_list = [{"sender": msg.sender, "content": msg.content, "timestamp": msg.timestamp.strftime("%H:%M")} for msg in messages]
    return jsonify({"success": True, "messages": msg_list}), 200

# ===== SocketIO Events =====
@socketio.on("join_chat")
def handle_join_chat(data):
    user1 = current_user.username
    user2 = data["receiver"]
    room = f"{min(user1, user2)}_{max(user1, user2)}"
    join_room(room)
    print(f"{user1} joined room {room}")

@socketio.on("private_message")
def handle_private_message(data):
    sender = current_user.username
    receiver = data["receiver"]
    message = data["message"]

    new_message = Message(sender=sender, receiver=receiver, content=message)
    db.session.add(new_message)
    db.session.commit()

    room = f"{min(sender, receiver)}_{max(sender, receiver)}"
    print("Sender:", sender)

    emit("new_message", {"sender": sender, "content": message, "timestamp": datetime.utcnow().strftime("%H:%M")}, room=room)

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)