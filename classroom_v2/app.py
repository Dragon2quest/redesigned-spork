from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, hashlib, random, string, os
from datetime import datetime, date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit
from email_utils import overdue_email, event_email, build_html, send_email

app = Flask(__name__)
app.secret_key = 'classconnect_v2_secret_2024'
DATABASE = 'classroom.db'

# ─── DB ───────────────────────────────────────────────
def get_db():
    c = sqlite3.connect(DATABASE)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with open('schema.sql') as f:
        c = get_db(); c.executescript(f.read()); c.commit(); c.close()

def hp(p): return hashlib.sha256(p.encode()).hexdigest()
def gen_code(): return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ─── SCHEDULER: check overdue assignments every hour ──
def check_overdue():
    conn = get_db()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        assignments = conn.execute(
            "SELECT * FROM assignments WHERE deadline <= ?", (now,)).fetchall()
        for a in assignments:
            non_submitters = conn.execute("""
                SELECT u.id, u.name, u.email FROM users u
                JOIN enrollments e ON u.id=e.student_id
                WHERE e.class_id=?
                AND u.id NOT IN (SELECT student_id FROM submissions WHERE assignment_id=?)
            """, (a['class_id'], a['id'])).fetchall()

            cfg = conn.execute("""
                SELECT ec.gmail, ec.app_password FROM email_config ec
                JOIN classes c ON ec.teacher_id=c.teacher_id WHERE c.id=?
            """, (a['class_id'],)).fetchone()

            for s in non_submitters:
                already = conn.execute(
                    "SELECT id FROM overdue_sent WHERE student_id=? AND assignment_id=?",
                    (s['id'], a['id'])).fetchone()
                if already: continue

                # In-app notification
                conn.execute("INSERT INTO notifications(user_id,message) VALUES(?,?)",
                    (s['id'], f'⚠️ OVERDUE: "{a["title"]}" was due {a["deadline"][:16]}. Submit immediately!'))
                conn.execute("INSERT INTO overdue_sent(student_id,assignment_id) VALUES(?,?)",
                    (s['id'], a['id']))

                # Email if configured
                if cfg and s['email']:
                    overdue_email(s['name'], a['title'], a['deadline'][:16],
                                  cfg['gmail'], cfg['app_password'], s['email'])
        conn.commit()
    except Exception as e:
        print(f"[Scheduler Error] {e}")
    finally:
        conn.close()

scheduler = BackgroundScheduler()
scheduler.add_job(func=check_overdue, trigger=IntervalTrigger(hours=1))
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# ─── HELPERS ──────────────────────────────────────────
def teacher_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'teacher': return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def student_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'student': return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def get_teacher_class(conn):
    return conn.execute('SELECT * FROM classes WHERE teacher_id=?', (session['user_id'],)).fetchone()

def notify_class(conn, class_id, message):
    students = conn.execute('SELECT student_id FROM enrollments WHERE class_id=?', (class_id,)).fetchall()
    for s in students:
        conn.execute('INSERT INTO notifications(user_id,message) VALUES(?,?)', (s['student_id'], message))

# ─── AUTH ─────────────────────────────────────────────
@app.route('/')
def landing(): return render_template('landing.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name, email, password, role = (request.form['name'].strip(),
            request.form['email'].strip().lower(),
            hp(request.form['password']), request.form['role'])
        conn = get_db()
        try:
            if conn.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone():
                flash('Email already registered!','error'); return render_template('register.html')

            if role == 'teacher':
                staff_id = request.form.get('staff_id','').strip().upper()
                if not staff_id: flash('Staff ID required!','error'); return render_template('register.html')
                if conn.execute('SELECT id FROM users WHERE staff_id=?',(staff_id,)).fetchone():
                    flash('Staff ID already taken!','error'); return render_template('register.html')
                conn.execute('INSERT INTO users(name,staff_id,email,password,role) VALUES(?,?,?,?,?)',
                             (name,staff_id,email,password,role))
                conn.commit()
                uid = conn.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()['id']
                code = gen_code()
                while conn.execute('SELECT id FROM classes WHERE class_code=?',(code,)).fetchone(): code = gen_code()
                cname = request.form.get('class_name', f"{name}'s Class").strip()
                conn.execute('INSERT INTO classes(name,teacher_id,class_code) VALUES(?,?,?)',(cname,uid,code))
                conn.commit()
                flash(f'Registered! Your Class Code: {code} — Share this with students.','success')

            else:  # student
                usn = request.form.get('usn','').strip().upper()
                code = request.form.get('class_code','').strip().upper()
                if not usn: flash('USN is required!','error'); return render_template('register.html')
                if not code: flash('Class code is required!','error'); return render_template('register.html')
                if conn.execute('SELECT id FROM users WHERE usn=?',(usn,)).fetchone():
                    flash('USN already registered!','error'); return render_template('register.html')
                cls = conn.execute('SELECT id FROM classes WHERE class_code=?',(code,)).fetchone()
                if not cls: flash('Invalid class code!','error'); return render_template('register.html')
                conn.execute('INSERT INTO users(name,usn,email,password,role) VALUES(?,?,?,?,?)',
                             (name,usn,email,password,role))
                conn.commit()
                uid = conn.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()['id']
                conn.execute('INSERT INTO enrollments(student_id,class_id) VALUES(?,?)',(uid,cls['id']))
                conn.commit()
                flash('Registered! You have joined the class.','success')

            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Error: {e}','error')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        login_id = request.form['login_id'].strip()
        password  = hp(request.form['password'])
        conn = get_db()
        # Try USN → student, or staff_id/email → teacher
        user = (conn.execute('SELECT * FROM users WHERE usn=? AND password=?',(login_id.upper(),password)).fetchone() or
                conn.execute('SELECT * FROM users WHERE staff_id=? AND password=?',(login_id.upper(),password)).fetchone() or
                conn.execute('SELECT * FROM users WHERE email=? AND password=?',(login_id.lower(),password)).fetchone())
        conn.close()
        if user:
            session.update({'user_id':user['id'],'name':user['name'],'role':user['role'],
                           'usn': user['usn'] or '', 'staff_id': user['staff_id'] or ''})
            return redirect(url_for('teacher_dashboard' if user['role']=='teacher' else 'student_dashboard'))
        flash('Invalid login ID or password.','error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('landing'))

# ─── TEACHER ROUTES ───────────────────────────────────
@app.route('/teacher')
@teacher_required
def teacher_dashboard():
    conn = get_db()
    cls  = get_teacher_class(conn)
    d    = {}
    if cls:
        cid = cls['id']
        d['students']    = conn.execute('SELECT COUNT(*) as c FROM enrollments WHERE class_id=?',(cid,)).fetchone()['c']
        d['notes']       = conn.execute('SELECT COUNT(*) as c FROM notes WHERE class_id=?',(cid,)).fetchone()['c']
        d['assignments'] = conn.execute('SELECT COUNT(*) as c FROM assignments WHERE class_id=?',(cid,)).fetchone()['c']
        d['groups']      = conn.execute('SELECT COUNT(*) as c FROM groups WHERE class_id=?',(cid,)).fetchone()['c']
        d['recent_notes'] = conn.execute('SELECT * FROM notes WHERE class_id=? ORDER BY created_at DESC LIMIT 4',(cid,)).fetchall()
        d['recent_assignments'] = conn.execute('SELECT * FROM assignments WHERE class_id=? ORDER BY created_at DESC LIMIT 4',(cid,)).fetchall()
        today = date.today().isoformat()
        d['attendance_today'] = conn.execute(
            "SELECT COUNT(*) as c FROM attendance WHERE class_id=? AND date=? AND status='present'",(cid,today)).fetchone()['c']
        d['upcoming_events'] = conn.execute(
            "SELECT * FROM events WHERE class_id=? AND event_date>=? ORDER BY event_date ASC LIMIT 3",(cid,today)).fetchall()
    conn.close()
    return render_template('teacher/dashboard.html', cls=cls, **d)

@app.route('/teacher/notes', methods=['GET','POST'])
@teacher_required
def teacher_notes():
    conn = get_db(); cls = get_teacher_class(conn)
    if request.method == 'POST':
        t,c = request.form['title'], request.form['content']
        conn.execute('INSERT INTO notes(class_id,teacher_id,title,content) VALUES(?,?,?,?)',
                     (cls['id'],session['user_id'],t,c))
        notify_class(conn, cls['id'], f'📄 New note posted: {t}')
        conn.commit(); flash('Note posted!','success')
    notes = conn.execute('SELECT * FROM notes WHERE class_id=? ORDER BY created_at DESC',(cls['id'],)).fetchall()
    conn.close()
    return render_template('teacher/notes.html', notes=notes, cls=cls)

@app.route('/teacher/notes/delete/<int:nid>')
@teacher_required
def delete_note(nid):
    conn = get_db()
    conn.execute('DELETE FROM notes WHERE id=? AND teacher_id=?',(nid,session['user_id']))
    conn.commit(); conn.close()
    flash('Note deleted.','success'); return redirect(url_for('teacher_notes'))

@app.route('/teacher/assignments', methods=['GET','POST'])
@teacher_required
def teacher_assignments():
    conn = get_db(); cls = get_teacher_class(conn)
    if request.method == 'POST':
        t,d,s,dl = (request.form['title'],request.form['description'],
                    request.form['subject'],request.form['deadline'])
        conn.execute('INSERT INTO assignments(class_id,teacher_id,title,description,subject,deadline) VALUES(?,?,?,?,?,?)',
                     (cls['id'],session['user_id'],t,d,s,dl))
        notify_class(conn, cls['id'], f'📝 New assignment: {t} | Due: {dl[:16]}')
        conn.commit(); flash('Assignment created!','success')
    assignments = conn.execute(
        '''SELECT a.*,(SELECT COUNT(*) FROM submissions WHERE assignment_id=a.id) as subs
           FROM assignments a WHERE a.class_id=? ORDER BY a.deadline ASC''',(cls['id'],)).fetchall()
    total_students = conn.execute('SELECT COUNT(*) as c FROM enrollments WHERE class_id=?',(cls['id'],)).fetchone()['c']
    conn.close()
    return render_template('teacher/assignments.html', assignments=assignments, cls=cls, total_students=total_students)

@app.route('/teacher/groups', methods=['GET','POST'])
@teacher_required
def teacher_groups():
    conn = get_db(); cls = get_teacher_class(conn)
    students = conn.execute(
        'SELECT u.id,u.name,u.usn FROM users u JOIN enrollments e ON u.id=e.student_id WHERE e.class_id=?',
        (cls['id'],)).fetchall()

    if request.method == 'POST':
        action = request.form['action']
        if action == 'create_random':
            gc   = int(request.form['group_count'])
            ids  = [s['id'] for s in students]; random.shuffle(ids)
            sz,rem = divmod(len(ids),gc); idx=0
            for i in range(gc):
                conn.execute('INSERT INTO groups(class_id,name,group_type) VALUES(?,?,?)',(cls['id'],f'Group {i+1}','random'))
                conn.commit()
                gid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                for _ in range(sz+(1 if i<rem else 0)):
                    if idx<len(ids): conn.execute('INSERT INTO group_members(group_id,student_id) VALUES(?,?)',(gid,ids[idx])); idx+=1
            conn.commit(); flash(f'{gc} random groups created!','success')
        elif action == 'create_specific':
            gname = request.form['group_name']; members = request.form.getlist('members')
            if not members: flash('Select at least one student.','error')
            else:
                conn.execute('INSERT INTO groups(class_id,name,group_type) VALUES(?,?,?)',(cls['id'],gname,'specific'))
                conn.commit()
                gid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                for m in members: conn.execute('INSERT OR IGNORE INTO group_members(group_id,student_id) VALUES(?,?)',(gid,m))
                conn.commit(); flash(f'Group "{gname}" created!','success')
        elif action == 'assign_topic':
            gid,t,s,desc,dl = (request.form['group_id'],request.form['topic_title'],
                request.form['subject'],request.form['description'],request.form['deadline'])
            conn.execute('INSERT INTO topics(group_id,title,subject,description,deadline) VALUES(?,?,?,?,?)',(gid,t,s,desc,dl))
            mems = conn.execute('SELECT student_id FROM group_members WHERE group_id=?',(gid,)).fetchall()
            grp  = conn.execute('SELECT name FROM groups WHERE id=?',(gid,)).fetchone()
            for m in mems: conn.execute('INSERT INTO notifications(user_id,message) VALUES(?,?)',
                (m['student_id'],f'🗂 New topic for {grp["name"]}: {t}'))
            conn.commit(); flash('Topic assigned!','success')

    groups_raw = conn.execute('SELECT * FROM groups WHERE class_id=? ORDER BY created_at DESC',(cls['id'],)).fetchall()
    groups = []
    for g in groups_raw:
        mems   = conn.execute('SELECT u.name,u.usn FROM users u JOIN group_members gm ON u.id=gm.student_id WHERE gm.group_id=?',(g['id'],)).fetchall()
        topics = conn.execute('SELECT * FROM topics WHERE group_id=?',(g['id'],)).fetchall()
        groups.append({'g':g,'members':mems,'topics':topics})
    conn.close()
    return render_template('teacher/groups.html', groups=groups, students=students, cls=cls)

@app.route('/teacher/submissions')
@teacher_required
def teacher_submissions():
    conn = get_db(); cls = get_teacher_class(conn)
    subs = conn.execute('''
        SELECT s.*,u.name as sname,u.usn,
               a.title as atitle,t.title as ttitle,g.name as gname
        FROM submissions s
        JOIN users u ON s.student_id=u.id
        LEFT JOIN assignments a ON s.assignment_id=a.id
        LEFT JOIN topics t ON s.topic_id=t.id
        LEFT JOIN groups g ON s.group_id=g.id
        WHERE (a.class_id=? OR g.class_id=?)
        ORDER BY s.submitted_at DESC''',(cls['id'],cls['id'])).fetchall()
    conn.close()
    return render_template('teacher/submissions.html', subs=subs, cls=cls)

# ── Attendance ──
@app.route('/teacher/attendance', methods=['GET','POST'])
@teacher_required
def teacher_attendance():
    conn = get_db(); cls = get_teacher_class(conn)
    sel_date = request.args.get('date', date.today().isoformat())
    students = conn.execute(
        'SELECT u.id,u.name,u.usn FROM users u JOIN enrollments e ON u.id=e.student_id WHERE e.class_id=? ORDER BY u.name',
        (cls['id'],)).fetchall()

    if request.method == 'POST':
        att_date = request.form['att_date']
        for s in students:
            status = request.form.get(f'status_{s["id"]}','absent')
            conn.execute('''INSERT INTO attendance(class_id,student_id,date,status) VALUES(?,?,?,?)
                            ON CONFLICT(student_id,class_id,date) DO UPDATE SET status=excluded.status''',
                         (cls['id'],s['id'],att_date,status))
        conn.commit()
        flash(f'Attendance saved for {att_date}!','success')
        sel_date = att_date

    # Load existing records for selected date
    existing = {}
    for row in conn.execute('SELECT student_id,status FROM attendance WHERE class_id=? AND date=?',(cls['id'],sel_date)).fetchall():
        existing[row['student_id']] = row['status']

    # Summary: last 7 days
    summary = conn.execute('''
        SELECT u.id,u.name,u.usn,
               SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as present_count,
               COUNT(a.id) as total_days
        FROM users u
        JOIN enrollments e ON u.id=e.student_id
        LEFT JOIN attendance a ON u.id=a.student_id AND a.class_id=e.class_id
        WHERE e.class_id=?
        GROUP BY u.id ORDER BY u.name''',(cls['id'],)).fetchall()

    conn.close()
    return render_template('teacher/attendance.html',
        cls=cls, students=students, sel_date=sel_date,
        existing=existing, summary=summary)

# ── Progress ──
@app.route('/teacher/progress')
@teacher_required
def teacher_progress():
    conn = get_db(); cls = get_teacher_class(conn)
    cid = cls['id']
    total_assignments = conn.execute('SELECT COUNT(*) as c FROM assignments WHERE class_id=?',(cid,)).fetchone()['c']
    total_topics      = conn.execute('SELECT COUNT(*) as c FROM topics t JOIN groups g ON t.group_id=g.id WHERE g.class_id=?',(cid,)).fetchone()['c']
    total_days        = conn.execute('SELECT COUNT(DISTINCT date) as c FROM attendance WHERE class_id=?',(cid,)).fetchone()['c']

    students = conn.execute(
        'SELECT u.id,u.name,u.usn FROM users u JOIN enrollments e ON u.id=e.student_id WHERE e.class_id=? ORDER BY u.name',
        (cid,)).fetchall()

    progress = []
    for s in students:
        subs_a = conn.execute('SELECT COUNT(*) as c FROM submissions WHERE student_id=? AND assignment_id IN (SELECT id FROM assignments WHERE class_id=?)',(s['id'],cid)).fetchone()['c']
        subs_t = conn.execute('SELECT COUNT(*) as c FROM submissions WHERE student_id=? AND topic_id IN (SELECT t.id FROM topics t JOIN groups g ON t.group_id=g.id WHERE g.class_id=?)',(s['id'],cid)).fetchone()['c']
        pres   = conn.execute("SELECT COUNT(*) as c FROM attendance WHERE student_id=? AND class_id=? AND status='present'",(s['id'],cid)).fetchone()['c']
        att_pct = round((pres/total_days)*100) if total_days>0 else 0
        a_pct   = round((subs_a/total_assignments)*100) if total_assignments>0 else 0
        t_pct   = round((subs_t/total_topics)*100) if total_topics>0 else 0
        overall = round((att_pct + a_pct + t_pct)/3)
        progress.append({'name':s['name'],'usn':s['usn'],'att':pres,'att_pct':att_pct,
                         'subs_a':subs_a,'a_pct':a_pct,'subs_t':subs_t,'t_pct':t_pct,'overall':overall})

    conn.close()
    return render_template('teacher/progress.html', cls=cls, progress=progress,
        total_assignments=total_assignments, total_topics=total_topics, total_days=total_days)

# ── Events ──
@app.route('/teacher/events', methods=['GET','POST'])
@teacher_required
def teacher_events():
    conn = get_db(); cls = get_teacher_class(conn)
    cfg  = conn.execute('SELECT * FROM email_config WHERE teacher_id=?',(session['user_id'],)).fetchone()

    if request.method == 'POST':
        title    = request.form['title']
        desc     = request.form['description']
        ev_date  = request.form['event_date']
        ev_type  = request.form['event_type']
        send_mail= request.form.get('send_email') == '1'

        conn.execute('INSERT INTO events(class_id,teacher_id,title,description,event_date,event_type) VALUES(?,?,?,?,?,?)',
                     (cls['id'],session['user_id'],title,desc,ev_date,ev_type))
        notify_class(conn, cls['id'], f'📅 {ev_type.title()}: {title} on {ev_date}')
        email_sent = False

        if send_mail and cfg:
            students = conn.execute(
                'SELECT u.email FROM users u JOIN enrollments e ON u.id=e.student_id WHERE e.class_id=? AND u.email IS NOT NULL',
                (cls['id'],)).fetchall()
            emails = [s['email'] for s in students]
            if emails:
                ok, _ = event_email(emails, title, ev_date, ev_type, desc, cfg['gmail'], cfg['app_password'])
                email_sent = ok
        elif send_mail and not cfg:
            flash('Configure Gmail first in Settings to send emails.','error')

        conn.execute('UPDATE events SET email_sent=? WHERE class_id=? AND title=? AND event_date=?',
                     (1 if email_sent else 0, cls['id'], title, ev_date))
        conn.commit()
        flash(f'Event added!{" Emails sent." if email_sent else ""}','success')

    events = conn.execute('SELECT * FROM events WHERE class_id=? ORDER BY event_date DESC',(cls['id'],)).fetchall()
    conn.close()
    return render_template('teacher/events.html', cls=cls, events=events, cfg=cfg)

# ── Email Settings ──
@app.route('/teacher/settings', methods=['GET','POST'])
@teacher_required
def teacher_settings():
    conn = get_db()
    cfg  = conn.execute('SELECT * FROM email_config WHERE teacher_id=?',(session['user_id'],)).fetchone()
    if request.method == 'POST':
        gmail = request.form['gmail'].strip()
        apw   = request.form['app_password'].strip()
        # Test connection
        ok, err = send_email(gmail, 'ClassConnect — Gmail Connected ✅',
            build_html('Gmail Connected!','<p>Your Gmail is now connected to ClassConnect. Automated emails will be sent from this address.</p>'),
            gmail, apw)
        if ok:
            conn.execute('''INSERT INTO email_config(teacher_id,gmail,app_password) VALUES(?,?,?)
                            ON CONFLICT(teacher_id) DO UPDATE SET gmail=excluded.gmail, app_password=excluded.app_password''',
                         (session['user_id'],gmail,apw))
            conn.commit()
            flash('Gmail connected! A test email was sent to your inbox.','success')
        else:
            flash(f'Connection failed: {err}. Make sure you use a Gmail App Password.','error')
    conn.close()
    return render_template('teacher/settings.html', cfg=cfg)

# ─── STUDENT ROUTES ───────────────────────────────────
@app.route('/student')
@student_required
def student_dashboard():
    conn = get_db()
    cls  = conn.execute(
        'SELECT c.*,u.name as tname FROM classes c JOIN enrollments e ON c.id=e.class_id JOIN users u ON c.teacher_id=u.id WHERE e.student_id=?',
        (session['user_id'],)).fetchone()
    notifs  = conn.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 15',(session['user_id'],)).fetchall()
    unread  = conn.execute('SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND is_read=0',(session['user_id'],)).fetchone()['c']
    today   = date.today().isoformat()
    events  = []
    if cls:
        events = conn.execute('SELECT * FROM events WHERE class_id=? AND event_date>=? ORDER BY event_date ASC LIMIT 5',(cls['id'],today)).fetchall()
    conn.execute('UPDATE notifications SET is_read=1 WHERE user_id=?',(session['user_id'],))
    conn.commit(); conn.close()
    return render_template('student/dashboard.html', cls=cls, notifs=notifs, unread=unread, events=events)

@app.route('/student/notes')
@student_required
def student_notes():
    conn = get_db()
    notes = conn.execute('''SELECT n.*,u.name as tname FROM notes n
        JOIN classes c ON n.class_id=c.id JOIN enrollments e ON c.id=e.class_id
        JOIN users u ON n.teacher_id=u.id WHERE e.student_id=? ORDER BY n.created_at DESC''',(session['user_id'],)).fetchall()
    conn.close(); return render_template('student/notes.html', notes=notes)

@app.route('/student/assignments', methods=['GET','POST'])
@student_required
def student_assignments():
    conn = get_db()
    if request.method == 'POST':
        aid, content = request.form['assignment_id'], request.form['content']
        if conn.execute('SELECT id FROM submissions WHERE assignment_id=? AND student_id=?',(aid,session['user_id'])).fetchone():
            flash('Already submitted!','error')
        else:
            conn.execute('INSERT INTO submissions(assignment_id,student_id,content) VALUES(?,?,?)',(aid,session['user_id'],content))
            conn.commit(); flash('Submitted!','success')
    assignments = conn.execute('''
        SELECT a.*,c.name as cname,
               (SELECT id FROM submissions WHERE assignment_id=a.id AND student_id=?) as submitted
        FROM assignments a JOIN classes c ON a.class_id=c.id
        JOIN enrollments e ON c.id=e.class_id WHERE e.student_id=? ORDER BY a.deadline ASC''',
        (session['user_id'],session['user_id'])).fetchall()
    conn.close(); return render_template('student/assignments.html', assignments=assignments)

@app.route('/student/groups', methods=['GET','POST'])
@student_required
def student_groups():
    conn = get_db()
    if request.method == 'POST':
        tid,gid,content = request.form['topic_id'],request.form['group_id'],request.form['content']
        if conn.execute('SELECT id FROM submissions WHERE topic_id=? AND student_id=?',(tid,session['user_id'])).fetchone():
            flash('Already submitted!','error')
        else:
            conn.execute('INSERT INTO submissions(topic_id,group_id,student_id,content) VALUES(?,?,?,?)',(tid,gid,session['user_id'],content))
            conn.commit(); flash('Submitted!','success')
    groups_raw = conn.execute(
        'SELECT g.*,c.name as cname FROM groups g JOIN group_members gm ON g.id=gm.group_id JOIN classes c ON g.class_id=c.id WHERE gm.student_id=?',
        (session['user_id'],)).fetchall()
    groups = []
    for g in groups_raw:
        mems   = conn.execute('SELECT u.name,u.usn FROM users u JOIN group_members gm ON u.id=gm.student_id WHERE gm.group_id=?',(g['id'],)).fetchall()
        topics = conn.execute('SELECT * FROM topics WHERE group_id=?',(g['id'],)).fetchall()
        td     = [{'t':t,'submitted':bool(conn.execute('SELECT id FROM submissions WHERE topic_id=? AND student_id=?',(t['id'],session['user_id'])).fetchone())} for t in topics]
        groups.append({'g':g,'members':mems,'topics':td})
    conn.close(); return render_template('student/groups.html', groups=groups)

@app.route('/student/attendance')
@student_required
def student_attendance():
    conn = get_db()
    cls  = conn.execute('SELECT c.* FROM classes c JOIN enrollments e ON c.id=e.class_id WHERE e.student_id=?',(session['user_id'],)).fetchone()
    records = []
    stats   = {'present':0,'absent':0,'late':0,'total':0,'pct':0}
    if cls:
        records = conn.execute('SELECT * FROM attendance WHERE student_id=? AND class_id=? ORDER BY date DESC',
                               (session['user_id'],cls['id'])).fetchall()
        for r in records:
            stats[r['status']] += 1; stats['total'] += 1
        if stats['total']: stats['pct'] = round((stats['present']/stats['total'])*100)
    conn.close()
    return render_template('student/attendance.html', records=records, stats=stats, cls=cls)

@app.route('/student/progress')
@student_required
def student_progress():
    conn = get_db()
    cls  = conn.execute('SELECT c.* FROM classes c JOIN enrollments e ON c.id=e.class_id WHERE e.student_id=?',(session['user_id'],)).fetchone()
    data = {}
    if cls:
        cid = cls['id']
        uid = session['user_id']
        total_a = conn.execute('SELECT COUNT(*) as c FROM assignments WHERE class_id=?',(cid,)).fetchone()['c']
        done_a  = conn.execute('SELECT COUNT(*) as c FROM submissions WHERE student_id=? AND assignment_id IN (SELECT id FROM assignments WHERE class_id=?)',(uid,cid)).fetchone()['c']
        total_t = conn.execute('SELECT COUNT(*) as c FROM topics t JOIN groups g ON t.group_id=g.id JOIN group_members gm ON g.id=gm.group_id WHERE g.class_id=? AND gm.student_id=?',(cid,uid)).fetchone()['c']
        done_t  = conn.execute('SELECT COUNT(*) as c FROM submissions WHERE student_id=? AND topic_id IN (SELECT t.id FROM topics t JOIN groups g ON t.group_id=g.id JOIN group_members gm ON g.id=gm.group_id WHERE g.class_id=? AND gm.student_id=?)',(uid,cid,uid)).fetchone()['c']
        total_d = conn.execute('SELECT COUNT(DISTINCT date) as c FROM attendance WHERE class_id=?',(cid,)).fetchone()['c']
        pres    = conn.execute("SELECT COUNT(*) as c FROM attendance WHERE student_id=? AND class_id=? AND status='present'",(uid,cid)).fetchone()['c']
        att_pct = round((pres/total_d)*100) if total_d else 0
        a_pct   = round((done_a/total_a)*100) if total_a else 0
        t_pct   = round((done_t/total_t)*100) if total_t else 0
        overall = round((att_pct+a_pct+t_pct)/3)
        # Recent submissions
        recent_subs = conn.execute('''
            SELECT s.*,a.title as atitle,t.title as ttitle FROM submissions s
            LEFT JOIN assignments a ON s.assignment_id=a.id
            LEFT JOIN topics t ON s.topic_id=t.id
            WHERE s.student_id=? ORDER BY s.submitted_at DESC LIMIT 10''',(uid,)).fetchall()
        data = dict(total_a=total_a,done_a=done_a,a_pct=a_pct,
                    total_t=total_t,done_t=done_t,t_pct=t_pct,
                    total_d=total_d,pres=pres,att_pct=att_pct,
                    overall=overall,recent_subs=recent_subs)
    conn.close()
    return render_template('student/progress.html', cls=cls, **data)

if __name__ == '__main__':
    if not os.path.exists(DATABASE): init_db()
    app.run(debug=True)
