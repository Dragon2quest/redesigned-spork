import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

BRAND_COLOR = "#6366f1"

def build_html(title, body_html, student_name=""):
    greeting = f"<p>Hi <strong>{student_name}</strong>,</p>" if student_name else ""
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#f9fafb;padding:0;border-radius:12px;overflow:hidden">
      <div style="background:{BRAND_COLOR};padding:24px 32px">
        <h1 style="color:#fff;margin:0;font-size:22px">🎓 ClassConnect</h1>
      </div>
      <div style="padding:32px;background:#fff">
        <h2 style="color:#111827;margin-top:0">{title}</h2>
        {greeting}
        {body_html}
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
        <p style="color:#9ca3af;font-size:13px">This is an automated message from ClassConnect. Do not reply to this email.</p>
      </div>
    </div>
    """

def send_email(to_email, subject, html_body, from_gmail, app_password):
    """Send a single email. Returns (success: bool, error: str|None)."""
    try:
        msg = MIMEMultipart('alternative')
        msg['From']    = f"ClassConnect <{from_gmail}>"
        msg['To']      = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ctx) as s:
            s.login(from_gmail, app_password)
            s.sendmail(from_gmail, to_email, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)

def send_bulk(to_emails, subject, html_body, from_gmail, app_password):
    """Send same email to multiple recipients."""
    errors = []
    for email in to_emails:
        ok, err = send_email(email, subject, html_body, from_gmail, app_password)
        if not ok:
            errors.append(f"{email}: {err}")
    return len(errors) == 0, errors

def overdue_email(student_name, assignment_title, deadline, from_gmail, app_password, to_email):
    body = f"""
    <p>Your assignment <strong style="color:#ef4444">"{assignment_title}"</strong> was due on 
    <strong>{deadline}</strong> and has not been submitted yet.</p>
    <p>Please submit it <strong>as soon as possible</strong> to avoid losing marks.</p>
    <a href="http://localhost:5000/student/assignments"
       style="display:inline-block;background:#6366f1;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;margin-top:8px">
       Submit Now →
    </a>
    """
    html = build_html("⚠️ Assignment Overdue", body, student_name)
    return send_email(to_email, f"⚠️ Overdue: {assignment_title}", html, from_gmail, app_password)

def event_email(recipients, event_title, event_date, event_type, description, from_gmail, app_password):
    icon = {"holiday": "🏖️", "exam": "📋", "event": "📅"}.get(event_type, "📅")
    body = f"""
    <div style="background:#f3f4f6;border-radius:8px;padding:16px;margin-bottom:16px">
      <div style="font-size:32px">{icon}</div>
      <h3 style="margin:8px 0 4px;color:#111827">{event_title}</h3>
      <div style="color:#6366f1;font-weight:bold">📅 {event_date}</div>
      <div style="display:inline-block;background:#e0e7ff;color:#4338ca;padding:2px 10px;border-radius:20px;font-size:12px;margin-top:4px">{event_type.upper()}</div>
    </div>
    {f'<p style="color:#374151">{description}</p>' if description else ''}
    """
    html = build_html(f"{icon} {event_title}", body)
    return send_bulk(recipients, f"{icon} {event_type.title()}: {event_title} on {event_date}",
                     html, from_gmail, app_password)
