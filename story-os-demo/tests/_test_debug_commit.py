import json
import tempfile
import shutil
from pathlib import Path
from system.obsidian_pull_service import ObsidianPullService
from tests.test_phase0c3c_obsidian_pull import _make_project_context

def test_commit_debug():
    temp_workspace = tempfile.mkdtemp()
    temp_vault = tempfile.mkdtemp()
    try:
        workspace = Path(temp_workspace)
        project_dir = workspace / "projects" / "test"
        project_dir.mkdir(parents=True)
        data_dir = project_dir / "data"
        data_dir.mkdir()
        (data_dir / "story_spec.json").write_text('{"title": "Test"}', encoding="utf-8")
        chapters_dir = data_dir / "chapters"
        chapters_dir.mkdir()
        target_dir = Path(temp_vault) / "StoryOS" / "test"
        target_dir.mkdir(parents=True, exist_ok=True)
        
        from system.obsidian_binding import ObsidianBinding, BindingStatus, BindingMarker, MARKER_FILENAME
        from system.obsidian_binding_store import ObsidianBindingStore
        from datetime import datetime, timezone
        binding = ObsidianBinding(
            binding_id="obs_test", project_id="test", timeline_id="main",
            vault_root=Path(temp_vault), target_relative_path="StoryOS/test",
            status=BindingStatus.BOUND,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        store = ObsidianBindingStore(workspace)
        store.save(binding)
        marker = BindingMarker(project_id="test", timeline_id="main", binding_id="obs_test")
        (target_dir / MARKER_FILENAME).write_text(json.dumps(marker.to_dict()), encoding="utf-8")
        
        ctx = _make_project_context(project_dir)
        
        base = b"# \u7b2c\u4e00\u7ae0\n\n\u8fd9\u662f\u539f\u59cb\u5185\u5bb9\u3002"
        obsidian = b"# \u7b2c\u4e00\u7ae0\n\n\u8fd9\u662f\u7528\u6237\u5728 Obsidian \u4fee\u6539\u540e\u7684\u5185\u5bb9\u3002"
        (chapters_dir / "chapter_001.md").write_bytes(base)
        (target_dir / "03_Chapters" / "chapter_001.md").parent.mkdir(parents=True, exist_ok=True)
        (target_dir / "03_Chapters" / "chapter_001.md").write_bytes(obsidian)
        
        from system.obsidian_mirror_manifest import MirrorManifestStore, build_empty_manifest, compute_content_hash, MirrorManifestEntry
        mstore = MirrorManifestStore(target_dir)
        manifest = mstore.load() or build_empty_manifest("obs_test", "test", "main")
        manifest.files["03_Chapters/chapter_001.md"] = MirrorManifestEntry(
            source_id="03_Chapters/chapter_001.md",
            content_hash=compute_content_hash(base),
            size_bytes=len(base),
            last_synced_at="2024-01-01T00:00:00",
        )
        mstore.save(manifest)
        
        service = ObsidianPullService(binding, ctx)
        preview = service.preview_file("03_Chapters/chapter_001.md")
        print(f"preview importable={preview.importable}")
        
        result = service.import_file("03_Chapters/chapter_001.md", preview.obsidian_hash)
        print(f"result status={result.status}")
        print(f"result commit_result={result.commit_result}")
        
        source_after = (chapters_dir / "chapter_001.md").read_bytes()
        print(f"source_after={source_after.decode('utf-8')}")
        
        # Check temp version file
        temp_version = project_dir / "data" / "manual" / "chapter_001_obsidian_pull_v001.json"
        if temp_version.exists():
            print(f"temp_version exists!")
            print(temp_version.read_text(encoding="utf-8"))
        else:
            print(f"temp_version does NOT exist")
    finally:
        shutil.rmtree(temp_workspace, ignore_errors=True)
        shutil.rmtree(temp_vault, ignore_errors=True)

test_commit_debug()
