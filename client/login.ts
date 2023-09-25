
const vars = document.getElementById('exp-vars')!.dataset as {[name: string]: string};

const node = document.getElementById('login-wrapper') as HTMLDivElement;
const button = document.getElementById('login-btn') as HTMLButtonElement;
const userid = document.getElementById('login-userid') as HTMLInputElement;
const password = document.getElementById('login-password') as HTMLInputElement;

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
    } catch (e) {
        if (e instanceof Error) {
            console.log(`login error: ${e.message}`);
            // bad credentials? account locked?
            //await this.msgDlg.show(`Error: ${e.message}`)
        }
    }
});

async function fetchApi(cmd: string, args: { [key: string]: any } = {}) {
    const headers = new Headers();
    headers.append('Content-Type', 'application/json');
    headers.append('Cache-Control', 'no-cache');
    const init = {
      method: 'POST',
      // Include cookies (i.e., the session id)
      credentials: 'same-origin',
      // Only send requests to a same-origin destination
      mode: 'same-origin',
      headers: headers,
      body: JSON.stringify(args)
    } as RequestInit;
  
    // NB: fetch() only rejects on, e.g., network failure, not on
    // HTTP error status
    console.log('sending command:', `/${vars.exp_url_prefix}/${cmd}`);
    const resp = await fetch(`/${vars.exp_url_prefix}/${cmd}`, init);
    if (!resp.ok) {
      // we got an error page from flask
      document.documentElement.innerHTML = await resp.text();
      throw new Error(
        `fetchApi('${cmd}'): bad response (${resp.status})`);
    }
    // The server returns an object with the following possible shapes:
    // - {err: 'error message'}
    // - {val: <successful return value>}
    // - {}  // no error, but no return value
    const json = await resp.json();
    if (json.err) {
      throw new Error(json.err);
    } else {
      return json.val;
    }
  }
  