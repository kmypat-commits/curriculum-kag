"""
Database initialization script
Creates initial admin user and roles
"""
import bcrypt
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type('about', (object,), {'__version__': bcrypt.__version__})

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app.models.user import User, Role, Permission
from app.services.auth import get_password_hash


def init_db():
    """Initialize database with tables and seed data"""
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # Delete existing admin if exists
        existing_admin = db.query(User).filter(User.email == "admin@curriculum-kag.local").first()
        if existing_admin:
            print("Deleting existing admin user...")
            db.delete(existing_admin)
            db.commit()
        
        # Create permissions
        permissions = [
            Permission(name="manage_users", resource="users", action="*"),
            Permission(name="manage_repository", resource="repository", action="*"),
            Permission(name="create_projects", resource="projects", action="create"),
            Permission(name="edit_projects", resource="projects", action="update"),
            Permission(name="view_projects", resource="projects", action="read"),
            Permission(name="delete_projects", resource="projects", action="delete"),
            Permission(name="view_analytics", resource="analytics", action="read"),
        ]
        
        for perm in permissions:
            db.add(perm)
        
        db.flush()
        
        # Create roles
        admin_role = Role(
            name="admin",
            description="Administrator with full access"
        )
        admin_role.permissions = permissions
        
        methodist_role = Role(
            name="methodist",
            description="Methodist/Expert for creating and editing programs"
        )
        methodist_role.permissions = [p for p in permissions if p.resource in ["projects", "repository"]]
        
        analyst_role = Role(
            name="analyst",
            description="Analyst for viewing metrics and reports"
        )
        analyst_role.permissions = [p for p in permissions if p.action == "read"]
        
        guest_role = Role(
            name="guest",
            description="Guest with read-only access"
        )
        guest_role.permissions = [p for p in permissions if p.action == "read"]
        
        db.add_all([admin_role, methodist_role, analyst_role, guest_role])
        db.flush()
        
        # Create admin user
        admin_user = User(
            email="admin@curriculum-kag.local",
            full_name="System Administrator",
            hashed_password=get_password_hash("admin123"),
            is_active=1,
            language="ru"
        )
        admin_user.roles = [admin_role]
        
        db.add(admin_user)
        db.commit()
        
        print("Database initialized successfully!")
        print("Admin user created:")
        print("  Email: admin@curriculum-kag.local")
        print("  Password: admin123")
        print("  IMPORTANT: Change this password after first login!")
        
    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
