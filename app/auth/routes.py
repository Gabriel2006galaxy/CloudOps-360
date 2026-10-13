from datetime import datetime, timezone
from urllib.parse import urlparse
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User, UserRole
from app.auth.forms import LoginForm, RegisterForm, ProfileForm
from app.services.audit import log_audit_event

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.username_or_email.data.strip()
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier.lower())
        ).first()

        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('This account has been deactivated. Please contact an administrator.', 'danger')
                log_audit_event(
                    action='AUTH_LOGIN_DEACTIVATED',
                    entity_type='User',
                    entity_id=user.id,
                    details=f"Deactivated account login attempt by '{identifier}'"
                )
                return render_template('auth/login.html', form=form)

            login_user(user, remember=form.remember_me.data)
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()

            log_audit_event(
                action='AUTH_LOGIN_SUCCESS',
                entity_type='User',
                entity_id=user.id,
                details=f"User '{user.username}' logged in successfully"
            )

            flash(f"Welcome back, {user.full_name}!", 'success')
            next_page = request.args.get('next')
            if not next_page or urlparse(next_page).netloc != '':
                next_page = url_for('dashboard.index')
            return redirect(next_page)
        else:
            log_audit_event(
                action='AUTH_LOGIN_FAILED',
                entity_type='User',
                details=f"Failed authentication attempt for '{identifier}'"
            )
            flash('Invalid username/email or password.', 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    user_id = current_user.id
    username = current_user.username
    logout_user()
    log_audit_event(
        action='AUTH_LOGOUT',
        entity_type='User',
        entity_id=user_id,
        details=f"User '{username}' logged out"
    )
    flash('You have been securely logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            full_name=form.full_name.data.strip(),
            username=form.username.data.strip(),
            email=form.email.data.strip().lower(),
            department=form.department.data.strip() if form.department.data else None,
            role=UserRole.EMPLOYEE,  # Strictly enforce Employee role for public registration
            is_active=True
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        log_audit_event(
            action='AUTH_REGISTER_SUCCESS',
            entity_type='User',
            entity_id=user.id,
            details=f"New user registered: '{user.username}' ({user.role})"
        )

        flash('Your account has been created successfully! Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.full_name = form.full_name.data.strip()
        current_user.department = form.department.data.strip() if form.department.data else None

        if form.new_password.data:
            if not form.current_password.data or not current_user.check_password(form.current_password.data):
                flash('Current password is required and must be correct to set a new password.', 'danger')
                return render_template('auth/profile.html', form=form)
            current_user.set_password(form.new_password.data)
            flash('Your password has been successfully updated.', 'success')

        db.session.commit()
        log_audit_event(
            action='USER_PROFILE_UPDATE',
            entity_type='User',
            entity_id=current_user.id,
            details=f"User '{current_user.username}' updated profile"
        )
        flash('Profile settings updated successfully.', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html', form=form)
