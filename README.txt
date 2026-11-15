============================================================
                 VINCI AI
             JTEG INTELLIGENCE PLATFORM
============================================================

Developed by:
Josiah Technologies and Engineering Group (JTEG)

Brand Statement:
ENGINEERING THE SYSTEMS THAT POWER MODERN CIVILIZATION

Made in Nigeria. Built for the World.


1. ABOUT VINCI AI
------------------------------------------------------------

Vinci AI is an artificial intelligence platform developed
under Josiah Technologies and Engineering Group (JTEG).

The platform is designed to provide users with access to
AI-powered assistance, creative tools, engineering design
workspaces, image capabilities, and voice-based interaction.

Vinci AI is intended for a broad range of users, including
students, professionals, creators, researchers, engineers,
and businesses.

The platform brings multiple AI-powered capabilities
together in one accessible workspace.


2. PLATFORM WORKSPACES
------------------------------------------------------------

Vinci AI includes the following main workspaces:

- Chat
  An AI conversation workspace for questions, explanations,
  research assistance, and general tasks.

- Design Studio
  A workspace for 2D drawing, 3D modelling, photo-to-design
  analysis, and engineering design visualisation.

- Image Studio
  An AI-powered workspace for image-related creative tasks.

- Voice
  A workspace for voice-based interaction.

Additional platform areas include:

- Images
- Library
- Projects
- Scheduled Reminders
- Plugins
- Settings
- Conversation History

Administrative database management is restricted to
authorised administrators.


3. USER ACCOUNTS
------------------------------------------------------------

Vinci AI is designed to support multiple independent users.

Users can create accounts and access their own workspaces.

Account features include:

- User registration
- Email verification
- Secure login
- Password recovery
- Persistent login sessions
- Private conversation history
- Personal workspace management

Users' conversations and saved work are intended to remain
available when they return to their accounts.


4. PRIVACY AND SECURITY
------------------------------------------------------------

User privacy is an important design requirement of
Vinci AI.

The platform is designed around the following principles:

- Users' private conversations must remain private.
- Each user must only access their own workspace.
- Administrative access must be restricted.
- Administrator account-management functions must not
  provide access to private user conversations.
- API keys and sensitive credentials must not be exposed
  in public source files or the application interface.
- Internal platform instructions and proprietary
  implementation details must not be exposed to users.

Security depends on correct application configuration,
secure hosting, database protection, and regular maintenance.

The application should undergo appropriate security
testing before large-scale public deployment.


5. CONFIGURATION
------------------------------------------------------------

The application requires appropriate configuration before
deployment.

Sensitive configuration values must be entered through
the hosting provider's private secrets-management system.

Never publish real API keys, passwords, SMTP credentials,
database credentials, or administrator credentials in
public repository files.

A sample configuration file may be provided for reference.
It must contain placeholders only.


6. DEPLOYMENT
------------------------------------------------------------

The project is designed for deployment using a compatible
Python application hosting environment.

General deployment procedure:

1. Upload the project files to the repository.
2. Configure the required private application secrets.
3. Install the dependencies listed in requirements.txt.
4. Configure the application entry point.
5. Deploy the application.
6. Test registration, email verification, login, logout,
   conversation history, and workspace functionality.
7. Verify that private user data is properly isolated.


7. DATA STORAGE AND CONTINUITY
------------------------------------------------------------

Conversation history, user information, and saved projects
require persistent database storage.

A temporary application session must not be treated as
permanent storage.

Production deployment should use a persistent database
with appropriate access controls, backups, and recovery
procedures.

Database backups and restoration procedures should be
tested regularly.


8. PROJECT FILES
------------------------------------------------------------

The repository contains the application and its supporting
configuration files.

Expected project files include:

- app.py
- requirements.txt
- logo.svg
- README.txt
- secrets.example.toml

Real credentials must never be stored in the public
repository.


9. IMPORTANT NOTICE
------------------------------------------------------------

Vinci AI is a JTEG-developed technology platform.

The platform's branding, identity, design, and proprietary
work are associated with Josiah Technologies and
Engineering Group.

This repository must not contain private credentials,
confidential user information, or proprietary internal
instructions.

Third-party services and libraries, where used, remain
subject to their respective licences and terms.

============================================================
       JOSIAH TECHNOLOGIES AND ENGINEERING GROUP
             MADE IN NIGERIA. BUILT FOR THE WORLD.
============================================================
