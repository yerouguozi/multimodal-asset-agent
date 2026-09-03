import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, FolderGit } from "lucide-react";
import {
  deleteAsset,
  fetchAssets,
  fetchDomainProfile,
  searchAssets,
  searchByImage,
  uploadFiles,
  fetchUsageSummary,
} from "../api";
import type { Asset, DomainProfile, UsageSummary } from "../types";
import AssetDetailModal from "../components/AssetDetailModal";
import AssetGrid from "../components/AssetGrid";
import ChatPanel from "../components/ChatPanel";
import DomainProfileCard from "../components/DomainProfileCard";
import SearchBar from "../components/SearchBar";
import UploadPanel from "../components/UploadPanel";

export default function Workspace() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [modality, setModality] = useState("");
  const [tag, setTag] = useState("");
  const [selected, setSelected] = useState<Asset | null>(null);
  const [profile, setProfile] = useState<DomainProfile | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);

  const notify = useCallback((m: string) => {
    setNotice(m);
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setNotice(""), 6000);
  }, []);

  const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const load = useCallback(async () => {
    try {
      const data = await fetchAssets({ modality, tag, pageSize: 50 });
      setAssets(data.items);
      setTotal(data.total);
    } catch (e) {
      notify(`加载素材失败：${errMsg(e)}`);
    }
  }, [modality, tag, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshMeta = useCallback(() => {
    fetchDomainProfile().then(setProfile).catch(() => undefined);
    fetchUsageSummary().then(setUsage).catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshMeta();
  }, [refreshMeta]);

  const handleSearch = async () => {
    if (!query.trim()) {
      await load();
      return;
    }
    setBusy(true);
    try {
      const r = await searchAssets(query.trim(), modality || undefined, tag || undefined);
      setAssets(r.hits.map((h) => h.asset));
      setTotal(r.hits.length);
    } catch (e) {
      notify(`搜索失败：${errMsg(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleReset = () => {
    setQuery("");
    void load();
  };

  const handleImageSearch = async (file: File) => {
    setBusy(true);
    try {
      const hits = await searchByImage(file);
      setAssets(hits.map((h) => h.asset));
      setTotal(hits.length);
      notify(hits.length ? `以图搜图：找到 ${hits.length} 个相似素材` : "没有找到相似素材");
    } catch (e) {
      notify(`以图搜图失败：${errMsg(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    try {
      const items = await uploadFiles(files);
      const msgs = items.map((it) => {
        if (it.error) return `失败：${it.error}`;
        if (it.duplicate_of != null) return `重复素材，已指向 #${it.duplicate_of}`;
        return `#${it.asset!.id} 已入库（${it.asset!.status}）`;
      });
      notify(msgs.join("；"));
      await load();
      refreshMeta();
    } catch (e) {
      notify(`上传失败：${errMsg(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("确定删除这个素材？删除后不可恢复。")) return;
    try {
      await deleteAsset(id);
      if (selected?.id === id) setSelected(null);
      notify(`已删除 #${id}`);
      await load();
      refreshMeta();
    } catch (e) {
      notify(`删除失败：${errMsg(e)}`);
    }
  };

  return (
    <div className="app workspace">
      <header className="app-header">
        <Link to="/" className="brand-link">
          <span className="brand-mark">M</span>
          <span className="brand-name">Multimodal Asset Agent</span>
        </Link>
        <span className="app-sub">上传什么，就长成什么的素材中心</span>
        <div className="header-right">
          <a
            className="ghost-chip"
            href="https://github.com/yerouguozi/multimodal-asset-agent"
            target="_blank"
            rel="noreferrer"
          >
            <FolderGit size={14} />
            GitHub
          </a>
          <Link className="ghost-chip" to="/">
            <ArrowLeft size={14} />
            介绍页
          </Link>
        </div>
      </header>

      {notice && <div className="notice">{notice}</div>}

      <main className="layout">
        <section className="left">
          <UploadPanel onUpload={handleUpload} busy={busy} />
          <SearchBar
            query={query}
            setQuery={setQuery}
            modality={modality}
            setModality={setModality}
            tag={tag}
            setTag={setTag}
            onSearch={handleSearch}
            onReset={handleReset}
            onImageSearch={handleImageSearch}
          />
          <AssetGrid assets={assets} total={total} onOpen={setSelected} onDelete={handleDelete} />
        </section>

        <aside className="right">
          <ChatPanel onComplete={() => { void load(); refreshMeta(); }} />
          <DomainProfileCard profile={profile} usage={usage} onRefresh={refreshMeta} />
        </aside>
      </main>

      {selected && (
        <AssetDetailModal asset={selected} onClose={() => setSelected(null)} onDelete={handleDelete} />
      )}
    </div>
  );
}
