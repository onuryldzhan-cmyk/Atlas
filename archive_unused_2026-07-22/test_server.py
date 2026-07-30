from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello():
    return '<h1>Atlas AI Test Server Calisiyor!</h1><p>Flask calisiyor, simdi dashboardu calistir.</p>'

if __name__ == '__main__':
    print('Test server baslatiliyor: http://127.0.0.1:9000')
    app.run(host='127.0.0.1', port=9000, debug=False)
