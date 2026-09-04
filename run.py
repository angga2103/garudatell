import os
from app import create_app

app = create_app()
app.config['TEMPLATES_AUTO_RELOAD'] = True

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"[*] Server GarudaTel berjalan dengan Auto-Reload di http://127.0.0.1:{port}/")
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
