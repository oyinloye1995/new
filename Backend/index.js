const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json()); // For parsing application/json

app.get('/', (req, res) => {
    res.send('Hello from the backend!');
});

app.listen(PORT, () => {
    console.log(`Server is running on http://localhost:${3000}`);
});
