import time
from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth.forms import LoginForm, ProfileForm, RegisterForm
from app.extensions import db
from app.models import User, UserRole, utcnow
from app.services.audit import client_ip, log_audit_event
from app.services.login_security import login_lock_status, record_login_attempt

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# Equalises response time for unknown users so usernames cannot be enumerated by timing
_DUMMY_HASH = None


def _safe_next(target):
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith('/') or target.startswith('//'):
        return None
    return target


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    global _DUMMY_HASH
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.username_or_email.data.strip()
        ip = client_ip()

        locked, retry_after, reason = login_lock_status(identifier, ip)
        if locked:
            log_audit_event('AUTH_LOGIN_LOCKED', 'User', None,
                            f"Sign-in blocked for '{identifier[:60]}' ({reason} rate limit)")
            minutes = max(1, (retry_after + 59) // 60)
            flash(f'Too many failed sign-in attempts. Try again in about {minutes} minute(s).', 'danger')
            return render_template('auth/login.html', form=form), 429

        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier.lower())
        ).first()

        if user is None:
            if _DUMMY_HASH is None:
                from werkzeug.security import generate_password_hash
                _DUMMY_HASH = generate_password_hash('timing-equaliser')
            from werkzeug.security import check_password_hash
            check_password_hash(_DUMMY_HASH, form.password.data)
            password_ok = False
        else:
            password_ok = user.check_password(form.password.data)

        if password_ok and not user.is_active:
            record_login_attempt(identifier, ip, success=False)
            log_audit_event('AUTH_LOGIN_DEACTIVATED', 'User', user.id,
                            f"Sign-in attempt to deactivated account '{user.username}'", user_id=user.id)
            flash('This account has been deactivated. Please contact an administrator.', 'danger')
            return render_template('auth/login.html', form=form), 403

        if not password_ok:
            record_login_attempt(identifier, ip, success=False)
            log_audit_event('AUTH_LOGIN_FAILED', 'User', user.id if user else None,
                            f"Failed sign-in for '{identifier[:60]}'", user_id=user.id if user else None)
            flash('Invalid username/email or password.', 'danger')
            return render_template('auth/login.html', form=form), 401

        # Success: rotate the session to prevent fixation, then sign in
        session.clear()
        login_user(user, remember=False)
        session.permanent = True
        session['login_at'] = session['last_seen'] = time.time()
        user.last_login_at = utcnow()
        db.session.commit()
        record_login_attempt(identifier, ip, success=True)
        log_audit_event('AUTH_LOGIN_SUCCESS', 'User', user.id, f"User '{user.username}' signed in")

        flash(f"Welcome back, {user.full_name}!", 'success')
        return redirect(_safe_next(request.args.get('next')) or url_for('dashboard.index'))

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    user_id, username = current_user.id, current_user.username
    logout_user()
    session.clear()
    log_audit_event('AUTH_LOGOUT', 'User', user_id, f"User '{username}' signed out", user_id=user_id)
    flash('You have been signed out securely.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if not current_app.config.get('ALLOW_SELF_REGISTRATION'):
        abort(404)
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            full_name=form.full_name.data.strip(),
            username=form.username.data.strip(),
            email=form.email.data.strip().lower(),
            department=form.department.data.strip() if form.department.data else None,
            role=UserRole.EMPLOYEE,  # never taken from the request: prevents privilege escalation
            is_active=True,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        log_audit_event('AUTH_REGISTER_SUCCESS', 'User', user.id,
                        f"New employee account registered: '{user.username}'", user_id=user.id)
        flash('Your account has been created. Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if request.method == 'GET':
        form.current_password.data = form.new_password.data = form.confirm_new_password.data = None

    if form.validate_on_submit():
        if form.new_password.data:
            if not form.current_password.data or not current_user.check_password(form.current_password.data):
                form.current_password.errors.append('Your current password is required to set a new one.')
                return render_template('auth/profile.html', form=form), 400
            current_user.set_password(form.new_password.data)
            log_audit_event('USER_PASSWORD_CHANGE', 'User', current_user.id,
                            f"User '{current_user.username}' changed their password", commit=False)

        # Only these two fields are ever read from the request: role/is_active cannot be changed here
        current_user.full_name = form.full_name.data.strip()
        current_user.department = form.department.data.strip() if form.department.data else None
        log_audit_event('USER_PROFILE_UPDATE', 'User', current_user.id,
                        f"User '{current_user.username}' updated their profile", commit=False)
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html', form=form)
