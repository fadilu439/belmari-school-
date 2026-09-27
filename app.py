from flask import Flask
import os
import psycopg2

app = Flask(__name__)

@app.route('/')
def home():
    return """
    <h1 style='text-align:center; color:green;'>BELMARI QUR'ANIC SCHOOL</h1>
    <h3 style='text-align:center;'>Website Yana Aiki!</h3>
    <p style='text-align:center;'><a href='/students'>Duba Dalibai</a></p>
    """

@app.route('/students')
def students():
    try:
        DATABASE_URL = os.environ.get('DATABASE_URL')
        if not DATABASE_URL:
            return "Database URL ba a saka ba a Render"
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT * FROM students LIMIT 5;")
        data = cur.fetchall()
        return f"<h2>An samu {len(data)} dalibai a database</h2><p>{data}</p>"
    except Exception as e:
        return f"Kuskure: {str(e)}"

if __name__ == '__main__':
    app.run()
