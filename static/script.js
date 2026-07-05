// Global variables
let stream = null;
let videoElement = null;
let canvasElement = null;
let faceCount = 0;
let currentStudentId = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    videoElement = document.getElementById('video');
    canvasElement = document.getElementById('canvas');
    
    // Set today's date
    document.getElementById('attendance-date').valueAsDate = new Date();
    document.getElementById('report-student').valueAsDate = new Date();
    
    // Tab navigation
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            switchTab(tabName);
        });
    });
    
    // Camera controls
    document.getElementById('startBtn').addEventListener('click', startCamera);
    document.getElementById('captureBtn').addEventListener('click', capturePhoto);
    document.getElementById('stopBtn').addEventListener('click', stopCamera);
    
    // Student management
    document.getElementById('addStudentForm').addEventListener('submit', addStudent);
    
    // Attendance
    document.getElementById('loadAttendanceBtn').addEventListener('click', loadAttendance);
    
    // Reports
    document.getElementById('generateReportBtn').addEventListener('click', generateReport);
    document.getElementById('markAttendanceBtn').addEventListener('click', markAttendance);
    
    // Load initial data
    loadStudents();
    loadStudentsForReports();
});

// Tab switching
function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active from all buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(tabName).classList.add('active');
    
    // Add active to clicked button
    event.target.classList.add('active');
    
    // Stop camera when leaving camera tab
    if (tabName !== 'camera' && stream) {
        stopCamera();
    }
}

// Camera functions
async function startCamera() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'user',
                width: { ideal: 640 },
                height: { ideal: 480 }
            },
            audio: false
        });
        
        videoElement.srcObject = stream;
        videoElement.onloadedmetadata = function() {
            videoElement.play();
        };
        
        document.getElementById('startBtn').disabled = true;
        document.getElementById('captureBtn').disabled = false;
        document.getElementById('stopBtn').disabled = false;
        
        showAlert('Camera started successfully', 'success');
        startFaceDetection();
    } catch (error) {
        showAlert('Error accessing camera: ' + error.message, 'error');
        console.error('Camera error:', error);
    }
}

function stopCamera() {
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        videoElement.srcObject = null;
        stream = null;
    }
    
    document.getElementById('startBtn').disabled = false;
    document.getElementById('captureBtn').disabled = true;
    document.getElementById('stopBtn').disabled = true;
    showAlert('Camera stopped', 'success');
}

function capturePhoto() {
    canvasElement.width = videoElement.videoWidth;
    canvasElement.height = videoElement.videoHeight;
    
    const ctx = canvasElement.getContext('2d');
    ctx.drawImage(videoElement, 0, 0);
    
    const imageData = canvasElement.toDataURL('image/jpeg');
    document.getElementById('capturedImg').src = imageData;
    document.getElementById('capturedImage').style.display = 'block';
    
    // Detect face
    detectFace(imageData);
    
    showAlert('Photo captured successfully', 'success');
}

// Face detection
async function detectFace(imageData) {
    try {
        const response = await fetch('/api/face-detection', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ image: imageData })
        });
        
        const data = await response.json();
        document.getElementById('face-count').textContent = `Faces Detected: ${data.faces_detected}`;
    } catch (error) {
        console.error('Face detection error:', error);
    }
}

function startFaceDetection() {
    setInterval(() => {
        if (videoElement.readyState === videoElement.HAVE_ENOUGH_DATA) {
            canvasElement.width = videoElement.videoWidth;
            canvasElement.height = videoElement.videoHeight;
            
            const ctx = canvasElement.getContext('2d');
            ctx.drawImage(videoElement, 0, 0);
            
            const imageData = canvasElement.toDataURL('image/jpeg');
            detectFace(imageData);
        }
    }, 2000); // Check every 2 seconds
}

// Student management
async function loadStudents() {
    try {
        const response = await fetch('/api/students');
        const students = await response.json();
        
        // Populate student select
        const select = document.getElementById('student-select');
        select.innerHTML = '<option value="">-- Select a Student --</option>';
        
        students.forEach(student => {
            const option = document.createElement('option');
            option.value = student.id;
            option.textContent = `${student.roll_number} - ${student.name}`;
            select.appendChild(option);
        });
        
        select.addEventListener('change', function() {
            currentStudentId = this.value;
            document.getElementById('markAttendanceBtn').disabled = !currentStudentId;
        });
        
        // Display students
        displayStudents(students);
    } catch (error) {
        showAlert('Error loading students: ' + error.message, 'error');
    }
}

function displayStudents(students) {
    const studentsList = document.getElementById('students-list');
    studentsList.innerHTML = '';
    
    students.forEach(student => {
        const card = document.createElement('div');
        card.className = 'student-card';
        card.innerHTML = `
            <h3>${student.name}</h3>
            <p><strong>Roll Number:</strong> ${student.roll_number}</p>
            <p><strong>Email:</strong> ${student.email}</p>
        `;
        studentsList.appendChild(card);
    });
}

async function addStudent(e) {
    e.preventDefault();
    
    const name = document.getElementById('student-name').value;
    const rollNumber = document.getElementById('student-roll').value;
    const email = document.getElementById('student-email').value;
    
    try {
        const response = await fetch('/api/students', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: name,
                roll_number: rollNumber,
                email: email
            })
        });
        
        if (response.ok) {
            showAlert('Student added successfully!', 'success');
            document.getElementById('addStudentForm').reset();
            loadStudents();
        } else {
            const error = await response.json();
            showAlert('Error: ' + error.error, 'error');
        }
    } catch (error) {
        showAlert('Error adding student: ' + error.message, 'error');
    }
}

// Attendance functions
async function markAttendance() {
    if (!currentStudentId) {
        showAlert('Please select a student', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/attendance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                student_id: currentStudentId,
                status: 'Present'
            })
        });
        
        if (response.ok) {
            showAlert('Attendance marked successfully!', 'success');
            document.getElementById('student-select').value = '';
            currentStudentId = null;
            document.getElementById('markAttendanceBtn').disabled = true;
            document.getElementById('capturedImage').style.display = 'none';
        } else {
            const error = await response.json();
            showAlert('Error: ' + error.error, 'error');
        }
    } catch (error) {
        showAlert('Error marking attendance: ' + error.message, 'error');
    }
}

async function loadAttendance() {
    const date = document.getElementById('attendance-date').value;
    
    if (!date) {
        showAlert('Please select a date', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/attendance/${date}`);
        const records = await response.json();
        
        const tbody = document.getElementById('attendance-tbody');
        tbody.innerHTML = '';
        
        records.forEach(record => {
            const row = document.createElement('tr');
            const statusClass = record.status === 'Present' ? 'status-present' : 'status-absent';
            row.innerHTML = `
                <td>${record.roll_number}</td>
                <td>${record.name}</td>
                <td class="${statusClass}">${record.status}</td>
                <td>${record.time_in}</td>
            `;
            tbody.appendChild(row);
        });
        
        showAlert('Attendance loaded successfully', 'success');
    } catch (error) {
        showAlert('Error loading attendance: ' + error.message, 'error');
    }
}

// Reports
async function loadStudentsForReports() {
    try {
        const response = await fetch('/api/students');
        const students = await response.json();
        
        const select = document.getElementById('report-student');
        select.innerHTML = '<option value="">-- Select a Student --</option>';
        
        students.forEach(student => {
            const option = document.createElement('option');
            option.value = student.id;
            option.textContent = `${student.roll_number} - ${student.name}`;
            select.appendChild(option);
        });
    } catch (error) {
        showAlert('Error loading students: ' + error.message, 'error');
    }
}

async function generateReport() {
    const studentId = document.getElementById('report-student').value;
    
    if (!studentId) {
        showAlert('Please select a student', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/attendance/report/${studentId}`);
        const data = await response.json();
        
        if (response.ok) {
            document.getElementById('report-name').textContent = data.name;
            document.getElementById('report-total').textContent = data.total;
            document.getElementById('report-present').textContent = data.present;
            document.getElementById('report-absent').textContent = data.absent;
            document.getElementById('report-percentage').textContent = data.percentage + '%';
            document.getElementById('report-card').style.display = 'block';
            
            showAlert('Report generated successfully', 'success');
        } else {
            showAlert('Error: ' + data.error, 'error');
        }
    } catch (error) {
        showAlert('Error generating report: ' + error.message, 'error');
    }
}

// Utility functions
function showAlert(message, type) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} show`;
    alertDiv.textContent = message;
    
    const container = document.querySelector('.container');
    container.insertBefore(alertDiv, container.firstChild);
    
    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

// Auto-refresh attendance count
function startAttendanceRefresh() {
    setInterval(() => {
        if (document.getElementById('attendance').classList.contains('active')) {
            const date = document.getElementById('attendance-date').value;
            if (date) {
                loadAttendance();
            }
        }
    }, 10000); // Refresh every 10 seconds
}