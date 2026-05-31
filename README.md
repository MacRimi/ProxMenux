<div align="center">
    <img src="https://github.com/MacRimi/ProxMenux/blob/main/images/main.png"
         alt="ProxMenux Logo"
         style="max-width: 100%; height: auto;" >
</div>

<br />

<div align="center">
    <a href="https://proxmenux.com/en" target="_blank">
        <img src="https://img.shields.io/badge/Website-%23E64804?style=for-the-badge&logo=World-Wide-Web&logoColor=white" alt="Website" />
    </a>
    <a href="https://proxmenux.com/en/docs/introduction" target="_blank">
        <img src="https://img.shields.io/badge/Docs-%232A3A5D?style=for-the-badge&logo=read-the-docs&logoColor=white" alt="Docs" />
    </a>
    <a href="https://proxmenux.com/en/changelog" target="_blank">
        <img src="https://img.shields.io/badge/Changelog-%232A3A5D?style=for-the-badge&logo=git&logoColor=white" alt="Changelog" />
    </a>
    <a href="https://proxmenux.com/en/guides" target="_blank">
        <img src="https://img.shields.io/badge/Guides-%232A3A5D?style=for-the-badge&logo=bookstack&logoColor=white" alt="Guides" />
    </a>
</div>

<div align="center" style="margin-top: 14px;">
    <a href="https://github.com/MacRimi/ProxMenux/releases/latest"><img src="https://img.shields.io/github/v/release/MacRimi/ProxMenux?display_name=tag&label=latest&color=2A3A5D&style=flat-square" alt="Latest release" /></a>
    <a href="https://github.com/MacRimi/ProxMenux/releases?q=prerelease%3Atrue"><img src="https://img.shields.io/github/v/release/MacRimi/ProxMenux?include_prereleases&label=beta&color=E64804&style=flat-square" alt="Latest beta" /></a>
    <a href="https://github.com/MacRimi/ProxMenux/blob/main/LICENSE"><img src="https://img.shields.io/github/license/MacRimi/ProxMenux?color=2A3A5D&style=flat-square&cacheSeconds=300" alt="License" /></a>
    <a href="https://github.com/MacRimi/ProxMenux/stargazers"><img src="https://img.shields.io/github/stars/MacRimi/ProxMenux?style=flat-square" alt="GitHub stars" /></a>
    <a href="https://github.com/MacRimi/ProxMenux/issues"><img src="https://img.shields.io/github/issues/MacRimi/ProxMenux?color=2A3A5D&style=flat-square" alt="Open issues" /></a>
</div>

<br />

<p align="center">
  <strong>ProxMenux</strong> is a management tool for <strong>Proxmox VE</strong> that simplifies system administration through an interactive menu, allowing you to execute commands and scripts with ease.
</p>

---

## 📌 Installation

To install ProxMenux, simply run the following command in your Proxmox server terminal:

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/MacRimi/ProxMenux/main/install_proxmenux.sh)"
```

> ⚠️ Be careful when copying scripts from the internet. Always remember to check the source!
>
> 📄 You can [review the source code](https://github.com/MacRimi/ProxMenux/blob/main/install_proxmenux.sh) before execution.
>
> 🛡️ All executable links follow our [Code of Conduct](https://github.com/MacRimi/ProxMenux?tab=coc-ov-file#-2-security--code-responsibility).

---

## 📌 How to Use

Once installed, launch **ProxMenux** by running:

```bash
menu
```

Then, follow the on-screen options to manage your Proxmox server efficiently.

---

## 🖥️ ProxMenux Monitor

ProxMenux Monitor is an integrated web dashboard that provides real-time visibility into your Proxmox infrastructure — accessible from any browser on your network, without needing a terminal.

**What it offers:**

- Real-time monitoring of CPU, RAM, disk usage and network traffic
- Overview of running VMs and LXC containers with status indicators
- Login authentication to protect access
- Two-Factor Authentication (2FA) with TOTP support
- Reverse proxy support (Nginx / Traefik)
- Designed to work across desktop and mobile devices

**Access:**

Once installed, the dashboard is available at:

```
http://<your-proxmox-ip>:8008
```

The Monitor is installed automatically as part of the standard ProxMenux installation and runs as a systemd service (`proxmenux-monitor.service`) that starts automatically on boot.

**Useful commands:**

```bash
# Check service status
systemctl status proxmenux-monitor

# View logs
journalctl -u proxmenux-monitor -n 50

# Restart the service
systemctl restart proxmenux-monitor
```

---

## 🧪 Beta Program

Want to try the latest features before the official release and help shape the final version?

The **ProxMenux Beta Program** gives early access to new functionality — including the newest builds of ProxMenux Monitor — directly from the `develop` branch. Beta builds may contain bugs or incomplete features. Your feedback is what helps fix them before the stable release.

**Install the beta version:**

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/MacRimi/ProxMenux/develop/install_proxmenux_beta.sh)"
```

**What to expect:**

- You'll get new features and Monitor builds before anyone else
- Some things may not work perfectly — that's expected and normal
- When a stable release is published, ProxMenux will notify you on the next `menu` launch and offer to switch automatically

**How to report issues:**

Open a [GitHub Issue](https://github.com/MacRimi/ProxMenux/issues) and include:
- What you did and what you expected to happen
- Any error messages shown on screen
- Logs from the Monitor if relevant:

```bash
journalctl -u proxmenux-monitor -n 50
```

> 💙 Thank you for being part of the beta program. Your help makes ProxMenux better for everyone.

---

## 🔧 Dependencies

The following dependencies are installed automatically during setup:

| Package | Purpose |
|---|---|
| `dialog` | Interactive terminal menus |
| `curl` | Downloads and connectivity checks |
| `jq` | JSON processing |
| `git` | Repository cloning and updates |
| `python3` + `python3-venv` | Translation support *(Translation version only)* |
| `googletrans` | Google Translate library *(Translation version only)* |

> **🛡️ Security Note / VirusTotal False Positive**
>
> If you scan the raw installation URL on VirusTotal, you might see a 1/95 detection by heuristic engines like *Chong Lua Dao*. This is a **known false positive**. Because this script uses the standard `curl | bash` installation pattern and downloads legitimate binaries (like `jq` from its official GitHub release), overly aggressive scanners flag the *behavior*. The script is 100% open source and safe to review. You can read more about this in [Issue #162](https://github.com/MacRimi/ProxMenux/issues/162).

---

## 🤝 Contributing

ProxMenux is an open, collaborative project — contributions of every shape are very welcome, no matter your background. Every PR, bug report, idea, translation or kind word helps move the project forward.

> 📖 **Before sending code**, please read the [**Contributing Guide**](CONTRIBUTING.md). It covers the project structure, the UI design policy (the two-phase `dialog` / `whiptail` flow), message helpers, translation policy and submission conventions — what reviewers will look for in your PR.

**Ways to help:**

- 💻 **Code** — fix a bug, polish a script, add a feature. Read the [Contributing Guide](CONTRIBUTING.md) first, then [open a pull request](https://github.com/MacRimi/ProxMenux/pulls).
- 🐛 **Bug reports** — found something broken? [Open an issue](https://github.com/MacRimi/ProxMenux/issues/new) with steps to reproduce, and the Monitor logs if relevant (`journalctl -u proxmenux-monitor -n 50`).
- 💡 **Ideas & feedback** — share suggestions in [GitHub Discussions](https://github.com/MacRimi/ProxMenux/discussions). Every idea is welcome.
- 🌍 **Translations** — the documentation site already supports English and Spanish; help expand it to more languages following the [translation guide](web/CONTRIBUTING-TRANSLATIONS.md) (one page per PR).
- 🧪 **Beta testing** — run the [beta build](#-beta-program) and let us know what you find.
- ⭐ **Spread the word** — a GitHub star or a mention in your homelab community helps others discover the project.

Before contributing, please take a moment to read our [Code of Conduct](https://github.com/MacRimi/ProxMenux?tab=coc-ov-file).

### Contributors

Thanks to everyone who has helped make ProxMenux what it is today.

<a href="https://github.com/MacRimi/ProxMenux/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=MacRimi/ProxMenux" alt="ProxMenux contributors" />
</a>

Made with [contrib.rocks](https://contrib.rocks).

---

## ⭐ Support the Project

If **ProxMenux** is useful to you, the simplest way to support it is a ⭐ on GitHub — it really helps others discover the project.

If you want to go a step further, a coffee on Ko-fi keeps development going:

<p>
  <a href="https://ko-fi.com/G2G313ECAN" target="_blank">
    <img src="https://img.shields.io/badge/Support%20on-Ko--fi-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white" alt="Support on Ko-fi" />
  </a>
</p>

---

## 📈 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=MacRimi/ProxMenux&type=Date)](https://www.star-history.com/#MacRimi/ProxMenux&Date)
