"""File handoffs and demo-only release/archiving."""
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from .core import InputError, digest_file, envelope, load_context, read_json, safe_path, save_module, utc_now, write_json
from .modules import register, read_tender, response_matrix, material_index, match_materials
from .documents import assemble, review_document

FILENAMES = {"M03": "source_manifest.json", "M04": "tender_brief.json", "M07": "response_matrix.json", "M08": "material_index.json", "M09": "asset_match.json", "M13": "assembly_result.json", "M14": "review_result.json"}


def execute(ctx, run_dir, stop=None, existing=False):
    values = {}
    ordered = list(FILENAMES)
    for module in ordered:
        filename = Path(run_dir) / FILENAMES[module]
        if existing and module != stop and filename.exists():
            values[module] = read_json(filename)
            continue
        if module == "M03":
            value = register(ctx)
        elif module == "M04":
            value = read_tender(ctx, values["M03"])
        elif module == "M07":
            value = response_matrix(ctx, values["M04"])
        elif module == "M08":
            value = material_index(ctx, values["M03"])
        elif module == "M09":
            value = match_materials(ctx, values["M04"], values["M07"], values["M08"])
        elif module == "M13":
            value = assemble(ctx, values["M04"], values["M07"], values["M08"], values["M09"], run_dir)
        else:
            value = review_document(ctx, values["M07"], values["M08"], values["M09"], values["M13"], run_dir)
        save_module(run_dir, FILENAMES[module], value)
        values[module] = value
        if module == "M03":
            save_module(run_dir, "project_register.json", value)
        if module == "M07":
            save_module(run_dir, "task_plan.json", value)
        if module == "M09":
            save_module(run_dir, "confirmed_selection.json", value)
        if stop == module:
            return values
    return values


def archive(ctx, run_dir):
    run_dir = Path(run_dir)
    files = []
    for path in sorted(run_dir.iterdir()):
        if path.is_file() and not path.name.startswith(".") and path.name not in ("archive_manifest.json", "archive_manifest.md", "archive.zip"):
            files.append({"relative_path": path.name, "sha256": digest_file(path)})
    registered = read_json(run_dir / "source_manifest.json")
    sources = registered["data"]["sources"]
    changed_source = any(not safe_path(ctx["input_root"], s["relative_path"]).is_file() or digest_file(safe_path(ctx["input_root"], s["relative_path"])) != s["sha256"] for s in sources)
    if changed_source or digest_file(safe_path(ctx["input_root"], "sources.json")) != registered["data"].get("sources_manifest_sha256") or any(not s.get("public", False) for s in sources):
        from .core import issue
        blocked = envelope(ctx, "M18", {"files": files, "source_files": sources, "public_export": False,
                                        "reuse_candidates_status": "NOT_APPROVED", "replay_boundary": "公开导出被阻断"},
                           issues=[issue("EXPORT_NOT_PERMITTED", "archive", "来源许可缺失、原件变化或登记策略变化，未生成公开包", owner="资料管理员")])
        save_module(run_dir, "archive_manifest.json", blocked)
        raise InputError("Public archive refused before export: source permissions missing or changed")
    value = envelope(ctx, "M18", {"files": files, "source_files": sources,
                                "public_export": True, "reuse_candidates_status": "NOT_APPROVED",
                                "replay_boundary": "DEMO原件与本次输出归档；无真实资料或复用授权"})
    save_module(run_dir, "archive_manifest.json", value)
    with zipfile.ZipFile(run_dir / "archive.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for item in files:
            z.write(run_dir / item["relative_path"], "outputs/" + item["relative_path"])
        z.write(run_dir / "archive_manifest.json", "archive_manifest.json")
        for source in sources:
            if not source.get("public", False):
                raise InputError("Source lacks explicit public export permission")
            path = safe_path(ctx["input_root"], source["relative_path"])
            if digest_file(path) != source["sha256"]:
                raise InputError("Source changed before archive")
            z.write(path, "inputs/" + source["relative_path"])
        for name in ("context.json", "sources.json", "template-manifest.json", "selection.json"):
            path = safe_path(ctx["input_root"], name)
            if path.is_file():
                z.write(path, "inputs/" + name)
    return value


def run(root, output, stop=None):
    output = Path(output)
    if output.exists():
        raise InputError("Output already exists; use a new run directory")
    ctx = load_context(root, "RUN-" + uuid.uuid4().hex[:12])
    output.mkdir(parents=True)
    write_json(output / ".context.json", ctx)
    values = execute(ctx, output, stop)
    write_json(output / "run_record.json", {"run_id": ctx["run_id"], "source_mode": "DEMO", "started_at": utc_now(),
                                            "modules": {m: v["processing_status"] for m, v in values.items()},
                                            "scope": "personnel_chapter_only", "workbuddy_runtime": "NOT_TESTED"})
    if not stop:
        archive(ctx, output)
    return values


def rerun_module(module, from_run, output):
    from_run, output = Path(from_run), Path(output)
    if module not in FILENAMES or output.exists():
        raise InputError("Unsupported module or output already exists")
    shutil.copytree(from_run, output)
    ctx = read_json(output / ".context.json")
    ctx["run_id"] = "RUN-" + uuid.uuid4().hex[:12]
    write_json(output / ".context.json", ctx)
    values = execute(ctx, output, module, existing=True)
    write_json(output / "rerun_record.json", {"module": module, "previous_run": from_run.name,
                                              "run_id": ctx["run_id"], "downstream_stale": list(FILENAMES)[list(FILENAMES).index(module) + 1:],
                                              "note": "本命令只重做指定模块，复制的下游输出不是本次有效结果"})
    for name in ("archive.zip", "archive_manifest.json", "archive_manifest.md"):
        path = output / name
        if path.exists():
            path.unlink()
    # Old releases cannot survive a changed run. Keep history in from_run.
    if (output / "release_record.json").exists():
        old = read_json(output / "release_record.json")
        old["status"] = "REVOKED"
        write_json(output / "release_record.json", old)
    return values


def release(run_dir, approver):
    if not approver.strip():
        raise InputError("Named approver required")
    run_dir = Path(run_dir)
    ctx = read_json(run_dir / ".context.json")
    if ctx["source_mode"] != "DEMO":
        raise InputError("Demo release only")
    rerun = read_json(run_dir / "rerun_record.json") if (run_dir / "rerun_record.json").exists() else None
    if rerun and rerun["module"] != "M14":
        raise InputError("Downstream outputs are stale after partial rerun; create a new complete run before release")
    registered = read_json(run_dir / FILENAMES["M03"])
    matrix, index, matched, assembled = [read_json(run_dir / FILENAMES[m]) for m in ("M07", "M08", "M09", "M13")]
    selected_ids = {p["person_id"] for p in matched["data"]["selected"]}
    selected_sources = {p["source_id"] for p in index["data"]["persons"] if p["person_id"] in selected_ids}
    selected_images = {a["relative_path"] for a in index["data"]["assets"] if a["person_id"] in selected_ids}
    for source in registered["data"]["sources"]:
        relevant = source["kind"] in ("tender_markdown", "template") or source["source_id"] in selected_sources or source["relative_path"] in selected_images
        if not relevant:
            continue
        path = safe_path(ctx["input_root"], source["relative_path"])
        if not path.is_file() or digest_file(path) != source["sha256"]:
            raise InputError("Registered input changed since this run; confirmation and release require a fresh run")
    if read_json(safe_path(ctx["input_root"], "selection.json")) != matched["data"]["confirmation"]["record"]:
        raise InputError("Selection confirmation changed since this run")
    if read_json(safe_path(ctx["input_root"], "template-manifest.json")) != matrix["data"]["template"]:
        raise InputError("Template manifest changed since this run")
    # 分工配置是 M07 新增声明输入：改了配置就要重跑，不能沿用按旧配置生成的矩阵放行。
    assignment = matrix["data"].get("task_assignment") or {}
    if assignment.get("configured"):
        path = safe_path(ctx["input_root"], assignment["file"])
        if not path.is_file() or digest_file(path) != assignment.get("sha256"):
            raise InputError("Task assignment configuration changed since this run; rerun before release")
    review = review_document(ctx, matrix, index, matched, assembled, run_dir)
    save_module(run_dir, FILENAMES["M14"], review)
    if review["issues"] or matched["data"]["confirmation"]["status"] != "CONFIRMED":
        raise InputError("Release refused: actual document or personnel confirmation has unresolved issues")
    value = {"schema_version": "bid-training.release.v1", "source_mode": "DEMO", "project_id": ctx["project_id"], "lot_id": ctx["lot_id"],
             "status": "RELEASED", "scope": "personnel_chapter_only", "sha256": review["data"]["file_sha256"],
             "approved_by": approver, "approved_at": utc_now(), "real_submission_authorized": False}
    write_json(run_dir / "release_record.json", value)
    archive(ctx, run_dir)
    return value
