"""
ProxMenux Monitor - VM/CT Backup Jobs API (Datacenter > Backup)

Blueprint Flask: wrapper sottile di `pvesh` su /cluster/backup, stessa logica
dello script shell vm_backup_jobs.sh. I job creati qui sono identici a quelli
della GUI nativa di Proxmox.

Endpoint (tutti sotto /api/vm-backup-jobs):
  GET    /                 lista job
  POST   /                 crea job
  GET    /options          storage con content "backup" + elenco VM/CT
  GET    /<id>             dettaglio job
  PUT    /<id>             modifica job
  DELETE /<id>             elimina job (gli archivi gia' fatti restano)
  POST   /<id>/toggle      abilita/disabilita
  POST   /<id>/run         esegue subito il backup (task in background)
"""

import json
import re
import subprocess

from flask import Blueprint, jsonify, request

vm_backup_jobs_bp = Blueprint("vm_backup_jobs", __name__)

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
STORAGE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
VMID_RE = re.compile(r"^\d+(,\d+)*$")
PRUNE_RE = re.compile(r"^[a-z0-9=,-]{1,120}$")
MODES = {"snapshot", "suspend", "stop"}
COMPRESS = {"0", "gzip", "lzo", "zstd"}


def _pvesh(args, timeout=25):
    """Esegue pvesh senza shell. Ritorna (ok, output)."""
    try:
        p = subprocess.run(
            ["pvesh", *args], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, "pvesh timeout"
    except FileNotFoundError:
        return False, "pvesh non trovato (serve un nodo Proxmox VE)"
    if p.returncode != 0:
        return False, (p.stderr or p.stdout).strip()
    return True, p.stdout


def _pvesh_json(args):
    ok, out = _pvesh([*args, "--output-format", "json"])
    if not ok:
        return False, out
    try:
        return True, json.loads(out or "null")
    except json.JSONDecodeError:
        return False, "risposta pvesh non valida"


def _normalize_job(job):
    """pvesh puo' restituire prune-backups come dict: lo riportiamo a stringa."""
    if isinstance(job, dict) and isinstance(job.get("prune-backups"), dict):
        job["prune-backups"] = ",".join(
            f"{k}={v}" for k, v in job["prune-backups"].items()
        )
    return job


def _err(msg, code=400):
    return jsonify({"success": False, "error": msg}), code


def _validate(data, partial=False):
    """Valida il payload e lo converte in argomenti pvesh. Ritorna (args, error)."""
    args = []
    deletes = []

    def has(k):
        return k in data and data[k] not in (None, "")

    if "all" in data or "vmid" in data:
        if data.get("all") in (1, True, "1", "true"):
            args += ["--all", "1"]
            deletes.append("vmid")
        else:
            vmid = str(data.get("vmid", "")).replace(" ", "")
            if not VMID_RE.match(vmid):
                return None, "Seleziona almeno una VM/CT (vmid non valido)"
            args += ["--vmid", vmid, "--all", "0"]
    elif not partial:
        return None, "Specifica 'all' oppure 'vmid'"

    if has("storage"):
        if not STORAGE_RE.match(str(data["storage"])):
            return None, "Storage non valido"
        args += ["--storage", str(data["storage"])]
    elif not partial:
        return None, "Storage obbligatorio"

    if has("schedule"):
        sched = str(data["schedule"]).strip()
        if len(sched) > 80 or sched.startswith("-"):
            return None, "Schedule non valido"
        args += ["--schedule", sched]
    elif not partial:
        return None, "Schedule obbligatorio"

    if has("mode"):
        if data["mode"] not in MODES:
            return None, "Modalita' non valida"
        args += ["--mode", data["mode"]]

    if has("compress"):
        if str(data["compress"]) not in COMPRESS:
            return None, "Compressione non valida"
        args += ["--compress", str(data["compress"])]

    if "prune_backups" in data:
        prune = str(data.get("prune_backups") or "").strip()
        if prune:
            if not PRUNE_RE.match(prune):
                return None, "Retention non valida (es. keep-last=3,keep-weekly=2)"
            args += ["--prune-backups", prune]
        else:
            deletes.append("prune-backups")

    if "notes_template" in data:
        notes = str(data.get("notes_template") or "").strip()
        if notes:
            if len(notes) > 512 or notes.startswith("-"):
                return None, "Note non valide"
            args += ["--notes-template", notes]
        else:
            deletes.append("notes-template")

    if "enabled" in data:
        args += ["--enabled", "1" if data["enabled"] in (1, True, "1", "true") else "0"]

    return (args, deletes), None


@vm_backup_jobs_bp.route("/api/vm-backup-jobs", methods=["GET"])
def list_jobs():
    ok, res = _pvesh_json(["get", "/cluster/backup"])
    if not ok:
        return _err(res, 500)
    return jsonify({"success": True, "jobs": [_normalize_job(j) for j in (res or [])]})


@vm_backup_jobs_bp.route("/api/vm-backup-jobs/options", methods=["GET"])
def options():
    ok, storages = _pvesh_json(["get", "/storage"])
    if not ok:
        return _err(storages, 500)
    ok, guests = _pvesh_json(["get", "/cluster/resources", "--type", "vm"])
    if not ok:
        return _err(guests, 500)
    return jsonify(
        {
            "success": True,
            "storages": [
                {"id": s["storage"], "type": s.get("type", "")}
                for s in storages
                if "backup" in (s.get("content") or "")
            ],
            "guests": sorted(
                [
                    {"vmid": g["vmid"], "name": g.get("name", "-"), "type": g["type"]}
                    for g in guests
                    if g.get("type") in ("qemu", "lxc")
                ],
                key=lambda g: g["vmid"],
            ),
        }
    )


@vm_backup_jobs_bp.route("/api/vm-backup-jobs", methods=["POST"])
def create_job():
    parsed, error = _validate(request.get_json(silent=True) or {})
    if error:
        return _err(error)
    args, _deletes = parsed
    ok, out = _pvesh(["create", "/cluster/backup", *args])
    if not ok:
        return _err(out, 500)
    return jsonify({"success": True})


@vm_backup_jobs_bp.route("/api/vm-backup-jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    if not ID_RE.match(job_id):
        return _err("ID non valido")
    ok, res = _pvesh_json(["get", f"/cluster/backup/{job_id}"])
    if not ok:
        return _err(res, 404)
    return jsonify({"success": True, "job": _normalize_job(res)})


@vm_backup_jobs_bp.route("/api/vm-backup-jobs/<job_id>", methods=["PUT"])
def update_job(job_id):
    if not ID_RE.match(job_id):
        return _err("ID non valido")
    parsed, error = _validate(request.get_json(silent=True) or {}, partial=True)
    if error:
        return _err(error)
    args, deletes = parsed
    for key in dict.fromkeys(deletes):  # senza duplicati
        args += ["--delete", key]
    ok, out = _pvesh(["set", f"/cluster/backup/{job_id}", *args])
    if not ok:
        return _err(out, 500)
    return jsonify({"success": True})


@vm_backup_jobs_bp.route("/api/vm-backup-jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    if not ID_RE.match(job_id):
        return _err("ID non valido")
    ok, out = _pvesh(["delete", f"/cluster/backup/{job_id}"])
    if not ok:
        return _err(out, 500)
    return jsonify({"success": True})


@vm_backup_jobs_bp.route("/api/vm-backup-jobs/<job_id>/toggle", methods=["POST"])
def toggle_job(job_id):
    if not ID_RE.match(job_id):
        return _err("ID non valido")
    ok, job = _pvesh_json(["get", f"/cluster/backup/{job_id}"])
    if not ok:
        return _err(job, 404)
    new_state = "0" if job.get("enabled", 1) in (1, True, "1") else "1"
    ok, out = _pvesh(["set", f"/cluster/backup/{job_id}", "--enabled", new_state])
    if not ok:
        return _err(out, 500)
    return jsonify({"success": True, "enabled": new_state == "1"})


@vm_backup_jobs_bp.route("/api/vm-backup-jobs/<job_id>/run", methods=["POST"])
def run_job(job_id):
    """Avvia vzdump con i parametri del job, staccato dal processo HTTP
    (cosi' un backup lungo non muore col timeout della richiesta)."""
    if not ID_RE.match(job_id):
        return _err("ID non valido")
    ok, job = _pvesh_json(["get", f"/cluster/backup/{job_id}"])
    if not ok:
        return _err(job, 404)
    job = _normalize_job(job)

    cmd = ["vzdump"]
    if job.get("all") in (1, True, "1"):
        cmd += ["--all", "1"]
    else:
        vmid = str(job.get("vmid", "")).replace(" ", "")
        if not VMID_RE.match(vmid):
            return _err("Il job non ha VM/CT selezionate")
        cmd += vmid.split(",")
    cmd += ["--storage", job.get("storage", ""), "--mode", job.get("mode", "snapshot")]
    cmd += ["--compress", str(job.get("compress", "zstd"))]
    if job.get("prune-backups"):
        cmd += ["--prune-backups", job["prune-backups"]]
    if job.get("notes-template"):
        cmd += ["--notes-template", job["notes-template"]]

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        return _err(f"Impossibile avviare vzdump: {e}", 500)
    return jsonify({"success": True, "message": "Backup avviato in background"})
