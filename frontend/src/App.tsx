import { useCallback, useEffect, useRef, useState } from "react";
import { deleteAsset, fetchAssets, fetchDomainProfile, searchAssets, uploadFiles } from "./api";
import type { Asset, DomainProfile } from "./types";
import AssetDetailModal from "./components/AssetDetailModal";
import AssetGrid from "./components/AssetGrid";
import ChatPanel from "./components/ChatPanel";
import DomainProfileCard from "./components/DomainProfileCard";
import SearchBar from "./components/SearchBar";
import UploadPanel from "./components/UploadPanel";

export default function App() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [modality, setModality] = useState("");
  const [tag, setTag] = useState("");
  const [selected, setSelected] = useState<Asset | null>(null);
  const [profile, setProfile] = useState<DomainProfile | null>(null);
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

  useEffect(() => {
    fetchDomainProfile().then(setProfile).catch(() => undefined);
  }, []);

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
      fetchDomainProfile().then(setProfile).catch(() => undefined);
    } catch (e) {
      notify(`删除失败：${errMsg(e)}`);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Multimodal Asset Agent</h1>
        <span className="app-sub">多模态素材中心 · 上传什么，就长成什么</span>
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
          />
          <AssetGrid assets={assets} total={total} onOpen={setSelected} onDelete={handleDelete} />
        </section>

        <aside className="right">
          <ChatPanel />
          <DomainProfileCard profile={profile} onRefresh={() => fetchDomainProfile().then(setProfile).catch(() => undefined)} />
        </aside>
      </main>

      {selected && (
        <AssetDetailModal asset={selected} onClose={() => setSelected(null)} onDelete={handleDelete} />
      )}
    </div>
  );
}
