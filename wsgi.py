"""
WSGI Entry Point untuk Production Deployment (Gunicorn)
File ini digunakan untuk menjalankan aplikasi Flask di production environment.

Usage:
    gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app
"""

from app import create_app

# Create Flask application instance
app = create_app()

if __name__ == '__main__':
    # Fallback untuk development (gunakan run.py untuk dev)
    app.run(host='0.0.0.0', port=5000, debug=False)
