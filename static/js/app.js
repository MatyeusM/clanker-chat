/* uid in localStorage, theme toggle, htmx4 boot + polling helpers. */
import "/static/js/htmx.esm.min.js";

const $ = (s) => document.querySelector(s);

// ---- theme: light-dark() follows color-scheme; toggle forces it ----
const root = document.documentElement;
root.dataset.theme = localStorage.getItem("theme") || "dark";
$("#theme-toggle")?.addEventListener("click", () => {
  root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("theme", root.dataset.theme);
});

// ---- identity: server-assigned int id, kept in localStorage ----
function params() {
  return new URLSearchParams(location.search);
}
let uid = localStorage.getItem("clanker_uid") || params().get("uid") || "";
let nick = localStorage.getItem("clanker_nick") || params().get("nick") || "";
if (params().get("uid")) localStorage.setItem("clanker_uid", params().get("uid"));
if (params().get("nick")) localStorage.setItem("clanker_nick", params().get("nick"));
uid = localStorage.getItem("clanker_uid") || "";
nick = localStorage.getItem("clanker_nick") || "";

const fUid = document.querySelector("#f-uid");
const fNick = document.querySelector("#f-nick");
if (fUid) fUid.value = uid;
if (fNick && !fNick.value) fNick.value = nick;
$("#join-form")?.addEventListener("submit", () => {
  localStorage.setItem("clanker_nick", $("#f-nick").value);
  $("#f-uid").value = localStorage.getItem("clanker_uid") || "";
});

// every htmx request carries identity (htmx4: detail.ctx.request.headers)
document.body.addEventListener("htmx:config:request", (e) => {
  const h = e.detail?.ctx?.request?.headers;
  if (!h) return;
  if (uid) h["X-User-Id"] = uid;
  h["X-Nickname"] = nick || $("#f-nick")?.value || "anon";
});

// landing: channel pills fill the join form instead of navigating
window.fillChannel = (name) => {
  const f = document.querySelector("#f-chan");
  if (f) f.value = name;
  const nick = document.querySelector("#f-nick");
  if (nick && !nick.value) nick.focus();
  else f?.focus();
};

// file input: highlight the clip icon while an attachment is staged
const sendForm = document.querySelector("#send");
const fileIn = sendForm?.querySelector('input[type="file"]');
const clipLabel = sendForm?.querySelector(".clip");
const markClip = () => {
  if (!clipLabel || !fileIn) return;
  clipLabel.classList.toggle("has-file", fileIn.files.length > 0);
  clipLabel.title = fileIn.files.length ? fileIn.files[0].name : "attach file";
};
fileIn?.addEventListener("change", markClip);
sendForm?.addEventListener("reset", () => setTimeout(markClip, 0));
window.lastMsgId = () => {
  const els = document.querySelectorAll("#log .msg[data-mid]");
  return els.length ? els[els.length - 1].dataset.mid : 0;
};
window.firstMsgId = () => {
  const el = document.querySelector("#log .msg[data-mid]");
  return el ? el.dataset.mid : 1000000000;
};
window.myUid = () => localStorage.getItem("clanker_uid") || "";

// autoscroll on new content (htmx4: detail.ctx.target)
document.body.addEventListener("htmx:after:swap", (e) => {
  const t = e.detail?.ctx?.target;
  if (t?.id === "log") t.scrollTop = 1e9;
});

// HX-Redirect responses navigate full-page; the chat page URL (?uid=&nick=)
// persists identity to localStorage on load (see top of file).

// ---- !command autocompletion ----
const CMDS = [
  ["!help", "list commands"],
  ["!nick", "rename: !nick <newname>"],
  ["!auth", "become owner: !auth <pw>"],
  ["!owner", "set owner pw: !owner <newpw>"],
  ["!setpassword", "lock/unlock: !setpassword <pw|off>"],
  ["!kick", "kick a user: !kick <nick>"],
];
const msgin = document.querySelector("#msgin");
const cbox = document.querySelector("#complete");
let csel = 0;
const bangToken = () => msgin?.value.match(/!(\w*)$/)?.[1] ?? null;
function renderComplete() {
  if (!msgin || !cbox) return;
  const t = bangToken();
  const hits = t === null ? [] : CMDS.filter(([c]) => c.startsWith("!" + t.toLowerCase()));
  if (!hits.length) {
    cbox.hidden = true;
    return;
  }
  csel = Math.min(csel, hits.length - 1);
  cbox.innerHTML = hits
    .map(
      ([c, d], i) =>
        `<button type="button" data-c="${c}" class="${i === csel ? "on" : ""}"><b>${c}</b> <span>${d}</span></button>`,
    )
    .join("");
  cbox.hidden = false;
  cbox.querySelectorAll("button").forEach((b) =>
    b.addEventListener("mousedown", (e) => {
      e.preventDefault();
      completeCmd(b.dataset.c);
    }),
  );
}
function completeCmd(cmd) {
  msgin.value = msgin.value.replace(/!\w*$/, cmd + " ");
  cbox.hidden = true;
  msgin.focus();
}
msgin?.addEventListener("input", () => {
  csel = 0;
  renderComplete();
});
msgin?.addEventListener("keydown", (e) => {
  if (!cbox || cbox.hidden) return;
  const btns = cbox.querySelectorAll("button");
  if (e.key === "ArrowDown") {
    e.preventDefault();
    csel = (csel + 1) % btns.length;
    renderComplete();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    csel = (csel + btns.length - 1) % btns.length;
    renderComplete();
  } else if (e.key === "Tab" || e.key === "Enter") {
    e.preventDefault();
    if (btns[csel]) completeCmd(btns[csel].dataset.c);
  } else if (e.key === "Escape") cbox.hidden = true;
});
document.querySelector("#send")?.addEventListener("submit", () => {
  if (cbox) cbox.hidden = true;
});
