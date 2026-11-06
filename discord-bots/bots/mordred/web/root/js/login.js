document.getElementById('loginBtn').addEventListener('click', function() {
    const token = document.getElementById('token').value;
    if (!token) {
        alert('Please enter a token.');
        return;
    }

    fetch('/login', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ token: token })
    })
    .then(response => {
        if (response.ok) {
            return response.json();
        } else {
            throw new Error('Login failed.');
        }
    })
    .then(data => {
        sessionStorage.setItem('adminToken', token);
        window.location.href = '/main';
    })
    .catch(error => {
        alert(error.message);
    });
});

function getAdminToken() {
    return sessionStorage.getItem('adminToken');
}

function authorizedFetch(url, options = {}) {
    const token = getAdminToken();
    if (!options.headers) {
        options.headers = {};
    }
    options.headers['Authorization'] = `Bearer ${token}`;
    return fetch(url, options);
}