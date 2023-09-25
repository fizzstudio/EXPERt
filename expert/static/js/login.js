const vars = document.getElementById('exp-vars').dataset;
document.getElementById('login-wrapper');
const button = document.getElementById('login-btn');
const userid = document.getElementById('login-userid');
const password = document.getElementById('login-password');
function updateLoginBtnDisabled() {
    console.log('updating button disabled state');
    button.disabled = !(userid.value.trim() && password.value);
}
userid.addEventListener('input', updateLoginBtnDisabled);
password.addEventListener('input', updateLoginBtnDisabled);
updateLoginBtnDisabled();
button.addEventListener('click', async () => {
    console.log('login button clicked');
    try {
        await fetchApi('login_creds', {
            userid: userid.value.trim(),
            password: password.value
        });
        location.href = `/${vars.exp_url_prefix}`;
    }
    catch (e) {
        if (e instanceof Error) {
            console.log(`login error: ${e.message}`);
        }
    }
});
async function fetchApi(cmd, args = {}) {
    const headers = new Headers();
    headers.append('Content-Type', 'application/json');
    headers.append('Cache-Control', 'no-cache');
    const init = {
        method: 'POST',
        credentials: 'same-origin',
        mode: 'same-origin',
        headers: headers,
        body: JSON.stringify(args)
    };
    console.log('sending command:', `/${vars.exp_url_prefix}/${cmd}`);
    const resp = await fetch(`/${vars.exp_url_prefix}/${cmd}`, init);
    if (!resp.ok) {
        document.documentElement.innerHTML = await resp.text();
        throw new Error(`fetchApi('${cmd}'): bad response (${resp.status})`);
    }
    const json = await resp.json();
    if (json.err) {
        throw new Error(json.err);
    }
    else {
        return json.val;
    }
}
//# sourceMappingURL=login.js.map
