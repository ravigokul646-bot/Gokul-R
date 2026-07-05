from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import cv2
import face_recognition
import numpy as np
import sqlite3
import os
from datetime import datetime, timedelta
import base64
from io import BytesIO
import json
import pickle
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import csv
from pathlib import Path

app = Flask(__name__)
CORS(app)

# Database setup
DB_NAME = 'attendance.db'
FACES_DIR = 'faces_data'
KNOWN_FACES_FILE = 'known_faces.pkl'

# Email Configuration (Update with your credentials)
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', 'your_email@gmail.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', 'your_app_password')
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

# Create directories
os.makedirs(FACES_DIR, exist_ok=True)

def init_db():
    """Initialize database with all required tables"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Students table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_number TEXT UNIQUE NOT NULL,
            email TEXT,
            phone TEXT,
            class TEXT,
            face_encoding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Attendance table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            attendance_date TEXT,
            time_in TEXT,
            time_out TEXT,
            status TEXT,
            face_match_score REAL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')
    
    # Logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== LOGGING ====================
def log_action(action, details):
    """Log all actions to database"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO logs (action, details) VALUES (?, ?)', 
                      (action, json.dumps(details)))
        conn.commit()
        conn.close()
        print(f"[LOG] {action}: {details}")
    except Exception as e:
        print(f"[ERROR] Logging failed: {e}")

# ==================== EMAIL NOTIFICATIONS ====================
def send_email(recipient_email, subject, body):
    """Send email notifications"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = recipient_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        log_action('EMAIL_SENT', {'recipient': recipient_email, 'subject': subject})
        return True
    except Exception as e:
        log_action('EMAIL_FAILED', {'recipient': recipient_email, 'error': str(e)})
        print(f"[ERROR] Email sending failed: {e}")
        return False

def send_attendance_notification(student):
    """Send attendance confirmation email"""
    subject = f"Attendance Marked - {datetime.now().strftime('%d-%m-%Y')}"
    body = f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>Attendance Confirmation</h2>
            <p>Dear <strong>{student['name']}</strong>,</p>
            <p>Your attendance has been marked for today.</p>
            <table style="border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px;"><strong>Roll Number:</strong></td>
                    <td style="padding: 8px;">{student['roll_number']}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;"><strong>Date:</strong></td>
                    <td style="padding: 8px;">{datetime.now().strftime('%d-%m-%Y')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;"><strong>Time:</strong></td>
                    <td style="padding: 8px;">{datetime.now().strftime('%H:%M:%S')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;"><strong>Status:</strong></td>
                    <td style="padding: 8px;"><span style="color: green;">Present</span></td>
                </tr>
            </table>
            <p style="margin-top: 20px; color: #666;">This is an automated message from the Attendance System.</p>
        </body>
    </html>
    """
    return send_email(student['email'], subject, body)

# ==================== FACE ENCODING MANAGEMENT ====================
def save_face_encoding(face_encoding, student_id):
    """Save face encoding to database"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        face_data = pickle.dumps(face_encoding)
        cursor.execute('UPDATE students SET face_encoding = ? WHERE id = ?',
                      (face_data, student_id))
        conn.commit()
        conn.close()
        log_action('FACE_ENCODING_SAVED', {'student_id': student_id})
        return True
    except Exception as e:
        log_action('FACE_ENCODING_FAILED', {'student_id': student_id, 'error': str(e)})
        return False

def get_face_encoding(student_id):
    """Retrieve face encoding from database"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT face_encoding FROM students WHERE id = ?', (student_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            return pickle.loads(result[0])
        return None
    except Exception as e:
        print(f"[ERROR] Getting face encoding: {e}")
        return None

# ==================== FACE RECOGNITION ====================
def recognize_face(image_data):
    """Recognize face and return matching student"""
    try:
        # Decode image
        image_bytes = base64.b64decode(image_data.split(',')[1])
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Convert to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Get face encodings
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
        
        if not face_encodings:
            return {'success': False, 'message': 'No face detected'}
        
        # Get all students
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, roll_number, email, face_encoding FROM students')
        students = cursor.fetchall()
        conn.close()
        
        best_match = None
        best_score = 0
        threshold = 0.6  # Face matching threshold
        
        # Compare with known faces
        for student in students:
            if student[4]:  # if face_encoding exists
                known_encoding = pickle.loads(student[4])
                distances = face_recognition.face_distance([known_encoding], face_encodings[0])
                
                if distances[0] < threshold:
                    match_score = 1 - distances[0]
                    if match_score > best_score:
                        best_score = match_score
                        best_match = {
                            'id': student[0],
                            'name': student[1],
                            'roll_number': student[2],
                            'email': student[3],
                            'match_score': round(match_score * 100, 2)
                        }
        
        if best_match:
            log_action('FACE_RECOGNIZED', {'student_id': best_match['id'], 'match_score': best_match['match_score']})
            return {'success': True, 'student': best_match, 'faces_detected': len(face_locations)}
        else:
            log_action('FACE_NOT_RECOGNIZED', {'faces_detected': len(face_locations)})
            return {'success': False, 'message': 'Face not recognized', 'faces_detected': len(face_locations)}
    
    except Exception as e:
        log_action('FACE_RECOGNITION_ERROR', {'error': str(e)})
        return {'success': False, 'message': f'Error: {str(e)}'}

# ==================== API ROUTES - STUDENTS ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/students', methods=['GET'])
def get_students():
    """Get all students with pagination"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Get total count
        cursor.execute('SELECT COUNT(*) FROM students')
        total = cursor.fetchone()[0]
        
        # Get paginated results
        offset = (page - 1) * per_page
        cursor.execute('''
            SELECT id, name, roll_number, email, phone, class, created_at 
            FROM students 
            ORDER BY roll_number 
            LIMIT ? OFFSET ?
        ''', (per_page, offset))
        
        students = cursor.fetchall()
        conn.close()
        
        return jsonify({
            'students': [{
                'id': s[0],
                'name': s[1],
                'roll_number': s[2],
                'email': s[3],
                'phone': s[4],
                'class': s[5],
                'created_at': s[6]
            } for s in students],
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        })
    except Exception as e:
        log_action('GET_STUDENTS_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

@app.route('/api/students', methods=['POST'])
def add_student():
    """Add new student"""
    try:
        data = request.json
        name = data.get('name')
        roll_number = data.get('roll_number')
        email = data.get('email')
        phone = data.get('phone', '')
        class_name = data.get('class', '')
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO students (name, roll_number, email, phone, class)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, roll_number, email, phone, class_name))
        conn.commit()
        student_id = cursor.lastrowid
        conn.close()
        
        log_action('STUDENT_ADDED', {'student_id': student_id, 'roll_number': roll_number})
        return jsonify({'message': 'Student added successfully', 'student_id': student_id}), 201
    except Exception as e:
        log_action('ADD_STUDENT_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

@app.route('/api/students/<int:student_id>', methods=['GET'])
def get_student(student_id):
    """Get student details"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, roll_number, email, phone, class, created_at 
            FROM students WHERE id = ?
        ''', (student_id,))
        
        student = cursor.fetchone()
        conn.close()
        
        if student:
            return jsonify({
                'id': student[0],
                'name': student[1],
                'roll_number': student[2],
                'email': student[3],
                'phone': student[4],
                'class': student[5],
                'created_at': student[6]
            })
        return jsonify({'error': 'Student not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/students/<int:student_id>', methods=['PUT'])
def update_student(student_id):
    """Update student details"""
    try:
        data = request.json
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE students 
            SET name = ?, email = ?, phone = ?, class = ?
            WHERE id = ?
        ''', (data.get('name'), data.get('email'), data.get('phone'), 
              data.get('class'), student_id))
        
        conn.commit()
        conn.close()
        
        log_action('STUDENT_UPDATED', {'student_id': student_id})
        return jsonify({'message': 'Student updated successfully'})
    except Exception as e:
        log_action('UPDATE_STUDENT_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

@app.route('/api/students/<int:student_id>', methods=['DELETE'])
def delete_student(student_id):
    """Delete student"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM students WHERE id = ?', (student_id,))
        conn.commit()
        conn.close()
        
        log_action('STUDENT_DELETED', {'student_id': student_id})
        return jsonify({'message': 'Student deleted successfully'})
    except Exception as e:
        log_action('DELETE_STUDENT_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

# ==================== API ROUTES - FACE ENCODING ====================
@app.route('/api/students/<int:student_id>/face-encoding', methods=['POST'])
def upload_face_encoding(student_id):
    """Upload and save face encoding for a student"""
    try:
        data = request.json
        image_data = data.get('image')
        
        # Decode image
        image_bytes = base64.b64decode(image_data.split(',')[1])
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Convert to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Get face encoding
        face_locations = face_recognition.face_locations(rgb_frame)
        if not face_locations:
            return jsonify({'error': 'No face detected'}), 400
        
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
        if not face_encodings:
            return jsonify({'error': 'Could not encode face'}), 400
        
        # Save encoding
        if save_face_encoding(face_encodings[0], student_id):
            log_action('FACE_ENCODING_UPLOADED', {'student_id': student_id})
            return jsonify({'message': 'Face encoding saved successfully', 'faces_detected': len(face_locations)})
        else:
            return jsonify({'error': 'Failed to save face encoding'}), 500
    
    except Exception as e:
        log_action('FACE_ENCODING_UPLOAD_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

# ==================== API ROUTES - ATTENDANCE ====================
@app.route('/api/attendance', methods=['POST'])
def mark_attendance():
    """Mark attendance for a student"""
    try:
        data = request.json
        student_id = data.get('student_id')
        status = data.get('status', 'Present')
        face_match_score = data.get('face_match_score', 0)
        notes = data.get('notes', '')
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        time_in = datetime.now().strftime('%H:%M:%S')
        
        # Check if already marked today
        cursor.execute('''
            SELECT id FROM attendance
            WHERE student_id = ? AND attendance_date = ?
        ''', (student_id, today))
        
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute('''
                UPDATE attendance
                SET time_in = ?, status = ?, face_match_score = ?, notes = ?
                WHERE student_id = ? AND attendance_date = ?
            ''', (time_in, status, face_match_score, notes, student_id, today))
        else:
            cursor.execute('''
                INSERT INTO attendance (student_id, attendance_date, time_in, status, face_match_score, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (student_id, today, time_in, status, face_match_score, notes))
        
        conn.commit()
        conn.close()
        
        # Get student details for email
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT name, email, roll_number FROM students WHERE id = ?', (student_id,))
        student = cursor.fetchone()
        conn.close()
        
        if student and student[1]:
            send_attendance_notification({
                'name': student[0],
                'email': student[1],
                'roll_number': student[2]
            })
        
        log_action('ATTENDANCE_MARKED', {'student_id': student_id, 'status': status})
        return jsonify({'message': 'Attendance marked successfully'}), 200
    except Exception as e:
        log_action('MARK_ATTENDANCE_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

@app.route('/api/attendance/<date>', methods=['GET'])
def get_attendance(date):
    """Get attendance for a specific date"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT s.id, s.name, s.roll_number, a.status, a.time_in, a.time_out, a.face_match_score
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id AND a.attendance_date = ?
            ORDER BY s.roll_number
        ''', (date,))
        
        records = cursor.fetchall()
        conn.close()
        
        return jsonify([{
            'student_id': r[0],
            'name': r[1],
            'roll_number': r[2],
            'status': r[3] or 'Absent',
            'time_in': r[4] or 'N/A',
            'time_out': r[5] or 'N/A',
            'face_match_score': r[6] or 0
        } for r in records])
    except Exception as e:
        log_action('GET_ATTENDANCE_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

@app.route('/api/attendance/report/<int:student_id>', methods=['GET'])
def get_student_report(student_id):
    """Get comprehensive attendance report for a student"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Get student info
        cursor.execute('''
            SELECT name, roll_number, email, class 
            FROM students WHERE id = ?
        ''', (student_id,))
        student_info = cursor.fetchone()
        
        if not student_info:
            return jsonify({'error': 'Student not found'}), 404
        
        # Get attendance statistics
        cursor.execute('''
            SELECT 
                COUNT(*) as total_days,
                COUNT(CASE WHEN status = 'Present' THEN 1 END) as present,
                COUNT(CASE WHEN status = 'Absent' THEN 1 END) as absent,
                COUNT(CASE WHEN status = 'Late' THEN 1 END) as late,
                AVG(face_match_score) as avg_match_score
            FROM attendance
            WHERE student_id = ?
        ''', (student_id,))
        
        stats = cursor.fetchone()
        
        # Get recent attendance
        cursor.execute('''
            SELECT attendance_date, status, time_in, face_match_score
            FROM attendance
            WHERE student_id = ?
            ORDER BY attendance_date DESC
            LIMIT 30
        ''', (student_id,))
        
        recent_attendance = cursor.fetchall()
        conn.close()
        
        total_days = stats[0] or 0
        present = stats[1] or 0
        absent = stats[2] or 0
        late = stats[3] or 0
        avg_score = round(stats[4], 2) if stats[4] else 0
        
        percentage = round((present / total_days * 100) if total_days > 0 else 0, 2)
        
        return jsonify({
            'name': student_info[0],
            'roll_number': student_info[1],
            'email': student_info[2],
            'class': student_info[3],
            'total_days': total_days,
            'present': present,
            'absent': absent,
            'late': late,
            'percentage': percentage,
            'avg_match_score': avg_score,
            'recent_attendance': [{
                'date': r[0],
                'status': r[1],
                'time_in': r[2],
                'face_match_score': r[3]
            } for r in recent_attendance]
        })
    except Exception as e:
        log_action('GET_REPORT_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

# ==================== API ROUTES - FACE DETECTION ====================
@app.route('/api/face-detection', methods=['POST'])
def detect_face():
    """Detect faces in image"""
    try:
        data = request.json
        image_data = data.get('image')
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data.split(',')[1])
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Convert to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Detect faces
        face_locations = face_recognition.face_locations(rgb_frame)
        
        return jsonify({
            'faces_detected': len(face_locations),
            'locations': face_locations
        })
    except Exception as e:
        log_action('FACE_DETECTION_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

@app.route('/api/face-recognition', methods=['POST'])
def face_recognition_api():
    """Recognize face and return matching student"""
    try:
        data = request.json
        image_data = data.get('image')
        
        result = recognize_face(image_data)
        return jsonify(result), 200 if result['success'] else 400
    except Exception as e:
        log_action('FACE_RECOGNITION_API_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

# ==================== API ROUTES - ANALYTICS ====================
@app.route('/api/analytics/dashboard', methods=['GET'])
def get_dashboard_analytics():
    """Get dashboard analytics"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Total students
        cursor.execute('SELECT COUNT(*) FROM students')
        total_students = cursor.fetchone()[0]
        
        # Today's attendance
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT COUNT(CASE WHEN status = 'Present' THEN 1 END),
                   COUNT(CASE WHEN status = 'Absent' THEN 1 END)
            FROM attendance WHERE attendance_date = ?
        ''', (today,))
        
        today_present, today_absent = cursor.fetchone()
        
        # This month's summary
        month_start = datetime.now().strftime('%Y-%m-01')
        cursor.execute('''
            SELECT COUNT(DISTINCT student_id)
            FROM attendance WHERE attendance_date >= ?
        ''', (month_start,))
        
        this_month_marked = cursor.fetchone()[0]
        
        # Average attendance
        cursor.execute('''
            SELECT AVG(percentage) FROM (
                SELECT 
                    student_id,
                    ROUND(COUNT(CASE WHEN status = 'Present' THEN 1 END) * 100.0 / 
                    COUNT(*), 2) as percentage
                FROM attendance
                GROUP BY student_id
            )
        ''')
        
        avg_attendance = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return jsonify({
            'total_students': total_students,
            'today_present': today_present or 0,
            'today_absent': today_absent or 0,
            'this_month_marked': this_month_marked,
            'avg_attendance': round(avg_attendance, 2)
        })
    except Exception as e:
        log_action('DASHBOARD_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

# ==================== API ROUTES - EXPORT ====================
@app.route('/api/export/attendance/<date>', methods=['GET'])
def export_attendance_csv(date):
    """Export attendance to CSV"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT s.roll_number, s.name, s.class, a.status, a.time_in, a.face_match_score
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id AND a.attendance_date = ?
            ORDER BY s.roll_number
        ''', (date,))
        
        records = cursor.fetchall()
        conn.close()
        
        # Create CSV
        output = BytesIO()
        writer = csv.writer(output)
        writer.writerow(['Roll Number', 'Name', 'Class', 'Status', 'Time In', 'Face Match %'])
        
        for record in records:
            writer.writerow([
                record[0], record[1], record[2],
                record[3] or 'Absent', record[4] or 'N/A',
                f"{record[5] or 0:.2f}%"
            ])
        
        output.seek(0)
        
        log_action('ATTENDANCE_EXPORTED', {'date': date})
        return send_file(output, mimetype='text/csv',
                        as_attachment=True,
                        download_name=f'attendance_{date}.csv')
    except Exception as e:
        log_action('EXPORT_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/student-report/<int:student_id>', methods=['GET'])
def export_student_report(student_id):
    """Export student report to CSV"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('SELECT name, roll_number FROM students WHERE id = ?', (student_id,))
        student = cursor.fetchone()
        
        if not student:
            return jsonify({'error': 'Student not found'}), 404
        
        cursor.execute('''
            SELECT attendance_date, status, time_in, time_out, face_match_score
            FROM attendance
            WHERE student_id = ?
            ORDER BY attendance_date DESC
        ''', (student_id,))
        
        records = cursor.fetchall()
        conn.close()
        
        # Create CSV
        output = BytesIO()
        writer = csv.writer(output)
        writer.writerow([f'Student: {student[0]} ({student[1]})'])
        writer.writerow([])
        writer.writerow(['Date', 'Status', 'Time In', 'Time Out', 'Face Match %'])
        
        for record in records:
            writer.writerow([
                record[0], record[1], record[2], record[3] or 'N/A',
                f"{record[4] or 0:.2f}%"
            ])
        
        output.seek(0)
        
        log_action('STUDENT_REPORT_EXPORTED', {'student_id': student_id})
        return send_file(output, mimetype='text/csv',
                        as_attachment=True,
                        download_name=f'report_{student[1]}.csv')
    except Exception as e:
        log_action('EXPORT_STUDENT_ERROR', {'error': str(e)})
        return jsonify({'error': str(e)}), 500

# ==================== API ROUTES - LOGS ====================
@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get system logs"""
    try:
        limit = request.args.get('limit', 100, type=int)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT action, details, timestamp
            FROM logs
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        
        logs = cursor.fetchall()
        conn.close()
        
        return jsonify([{
            'action': log[0],
            'details': json.loads(log[1]) if log[1] else {},
            'timestamp': log[2]
        } for log in logs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    log_action('INTERNAL_ERROR', {'error': str(error)})
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    log_action('SERVER_START', {'timestamp': datetime.now().isoformat()})
    app.run(debug=True, host='0.0.0.0', port=5000)