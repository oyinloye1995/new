const mysql = require('mysql2');

const connection = mysql.createConnection({
    host: 'localhost',
    user: 'root',
    password: '',
    database: 'my_database'
});

connection.connect((err) => {
    if (err) {
        console.error('Error connecting to MySQL:', err);
        return;
    }
    console.log('Connected to MySQL');
});

// Example query
connection.query('SELECT * FROM your_table_name', (err, results) => {
    if (err) throw err;
    console.log(results);
});

connection.end();
