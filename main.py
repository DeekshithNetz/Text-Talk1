from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, or_, and_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from typing import Dict, List
from zoneinfo import ZoneInfo

# ======================
# DB SETUP (SQLAlchemy)
# ======================
DATABASE_URL = "postgresql://neondb_owner:npg_Ssjl0dDwk9Zo@ep-falling-dream-atv775dp-pooler.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# ======================
# MODELS
# ======================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password = Column(String(100), nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    sender = Column(String(100), nullable=False)
    receiver = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(
    DateTime,
    default=lambda: datetime.now(ZoneInfo("Asia/Kolkata"))
)


Base.metadata.create_all(bind=engine)

# ======================
# FASTAPI APP
# ======================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://texttalk.checkman121.workers.dev"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================
# SIMPLE SESSION STORE (REPLACE FLASK-LOGIN)
# ======================
sessions: Dict[str, str] = {}  # session_id -> username

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Login required")

    username = sessions[session_id]
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user

# ======================
# AUTH ROUTES
# ======================
@app.post("/api/register")
def register(data: dict, db: Session = Depends(get_db)):
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return JSONResponse({"success": False, "message": "Username and password required"}, 400)

    if db.query(User).filter_by(username=username).first():
        return JSONResponse({"success": False, "message": "Username already exists"}, 400)

    user = User(username=username, password=password)
    db.add(user)
    db.commit()

    return {"success": True, "message": "User registered successfully"}


@app.post("/api/login")
def login(request: Request, data: dict, db: Session = Depends(get_db)):
    username = data.get("username")
    password = data.get("password")

    user = db.query(User).filter_by(username=username, password=password).first()

    if not user:
        return JSONResponse({"success": False, "message": "Invalid credentials"}, 401)

    import uuid
    session_id = str(uuid.uuid4())
    sessions[session_id] = username

    response = JSONResponse({"success": True, "message": "Login successful"})
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=True,
        samesite="none"
    )
    return response


@app.post("/api/logout")
def logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id in sessions:
        del sessions[session_id]

    response = JSONResponse({"success": True, "message": "Logged out"})
    response.delete_cookie("session_id")
    return response

# ======================
# USERS
# ======================
@app.get("/api/users")
def get_users(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)

    users = db.query(User).filter(User.id != user.id).all()
    return {
        "success": True,
        "users": [{"username": u.username} for u in users]
    }

# ======================
# MESSAGES
# ======================
@app.get("/api/messages/{receiver}")
def get_messages(receiver: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    sender = user.username

    messages = db.query(Message).filter(
        or_(
            and_(Message.sender == sender, Message.receiver == receiver),
            and_(Message.sender == receiver, Message.receiver == sender)
        )
    ).order_by(Message.timestamp).all()

    return {
        "success": True,
        "messages": [
            {
                "sender": m.sender,
                "content": m.content,
                "timestamp": m.timestamp.strftime("%H:%M")
            }
            for m in messages
        ]
    }

# ======================
# WEBSOCKET CHAT (SocketIO replacement)
# ======================
class ConnectionManager:
    def __init__(self):
        self.active_rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, room: str, websocket: WebSocket):
        await websocket.accept()
        self.active_rooms.setdefault(room, []).append(websocket)

    def disconnect(self, room: str, websocket: WebSocket):
        self.active_rooms[room].remove(websocket)

    async def broadcast(self, room: str, message: dict):
        for conn in self.active_rooms.get(room, []):
            await conn.send_json(message)


manager = ConnectionManager()

@app.websocket("/ws/chat/{receiver}")
async def chat_socket(websocket: WebSocket, receiver: str):

    db = SessionLocal()

    session_id = websocket.cookies.get("session_id")
    if session_id not in sessions:
        await websocket.close()
        return

    sender = sessions[session_id]
    room = f"{min(sender, receiver)}_{max(sender, receiver)}"

    await manager.connect(room, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            message_text = data["message"]

            msg = Message(
                sender=sender,
                receiver=receiver,
                content=message_text
            )
            db.add(msg)
            db.commit()

            await manager.broadcast(room, {
                "sender": sender,
                "content": message_text,
                "timestamp": datetime.now(
    ZoneInfo("Asia/Kolkata")
).strftime("%H:%M")
            })

    except WebSocketDisconnect:
        manager.disconnect(room, websocket)

    finally:
        db.close()