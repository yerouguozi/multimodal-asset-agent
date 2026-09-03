import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, ArrowLeft, FolderGit, LogOut, Trash2, UserCircle2, X } from "lucide-react";
import {
  clearAuth,
  deleteAsset,
  getUser,
  fetchAssets,
  fetchAsset,
  fetchDomainProfile,
  searchAssets,
  searchByImage,
  uploadFiles,
  fetchUsageSummary,
  restoreAsset,
  purgeAsset,
} from "../api";
import type { Asset, DomainProfile, UsageSummary } from "../types";
import AssetDetailModal from "../components/AssetDetailModal";
import AssetGrid from "../components/AssetGrid";
import ChatPanel from "../components/ChatPanel";
import DomainProfileCard from "../components/DomainProfileCard";
import SearchBar from "../components/SearchBar";
import UploadPanel from "../components/UploadPanel";

export default function Workspace() {
  const [user] = useState(() => getUser());
  const [assets, setAssets] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [modality, setModality] = useState("");
  const [tag, setTag] = useState("");
  const [selected, setSelected] = useState<Asset | null>(null);
  const [seekTarget, setSeekTarget] = useState<number | null>(null);
  const [profile, setProfile] = useState<DomainProfile | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [gridLoading, setGridLoading] = useState(true);
  const [imageSearched, setImageSearched] = useState(false);
  const [showTrash, setShowTrash] = useState(false);
  const [trashItems, setTrashItems] = useState<Asset[]>([]);
  const [trashBusy, setTrashBusy] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);

  const notify = useCallback((m: string) => {
    setNotice(m);
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setNotice(""), 6000);
  }, []);

  const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const runList = useCallback(
    async (m: string, t: string) => {
      setGridLoading(true);
      try {
        const data = await fetchAssets({ modality: m || undefined, tag: t || undefined, pageSize: 50 });
        setAssets(data.items);
        setTotal(data.total);
      } catch (e) {
        notify(`加载素材失败：${errMsg(e)}`);
      } finally {
        setGridLoading(false);
      }
    },
    [notify]
  );

  const runSearch = useCallback(
    async (q: string, m: string, t: string) => {
      setGridLoading(true);
      try {
        const r = await searchAssets(q, m || undefined, t || undefined);
        setAssets(r.hits.map((h) => h.asset));
        setTotal(r.hits.length);
      } catch (e) {
        notify(`搜索失败：${errMsg(e)}`);
      } finally {
        setGridLoading(false);
      }
    },
    [notify]
  );

  const load = useCallback(async () => {
    try {
      await runList(modality, tag);
    } catch (e) {
      // 错误已在 runList 内提示
      void e;
    }
  }, [modality, tag, runList]);

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
    const q = query.trim();
    if (q) {
      setImageSearched(false);
      await runSearch(q, modality, tag);
    } else {
      setImageSearched(false);
      await runList(modality, tag);
    }
  };

  const handleModalityChange = (m: string) => {
    setModality(m);
    setImageSearched(false);
    const q = query.trim();
    if (q) {
      void runSearch(q, m, tag);
    } else {
      void runList(m, tag);
    }
  };

  const refreshTrash = useCallback(async () => {
    try {
      const data = await fetchAssets({ pageSize: 100, deleted: true });
      setTrashItems(data.items);
    } catch {
      setTrashItems([]);
    }
  }, []);

  const toggleTrash = async () => {
    const next = !showTrash;
    setShowTrash(next);
    if (next) {
      setTrashBusy(true);
      await refreshTrash();
      setTrashBusy(false);
    }
  };

  const trashAction = async (id: number, restore: boolean) => {
    setTrashBusy(true);
    try {
      if (restore) {
        await restoreAsset(id);
        notify(`已恢复素材 #${id}`);
      } else {
        if (!window.confirm("彻底删除后文件与向量都会被移除，且不可恢复。确定？")) return;
        await purgeAsset(id);
        notify(`已彻底删除 #${id}`);
      }
      await refreshTrash();
      void load();
      refreshMeta();
    } catch (e) {
      notify(`操作失败：${errMsg(e)}`);
    } finally {
      setTrashBusy(false);
    }
  };

  const handleReset = () => {
    setQuery("");
    setModality("");
    setTag("");
    setImageSearched(false);
    void runList("", "");
  };

  const handleImageSearch = async (file: File) => {
    setGridLoading(true);
    setImageSearched(true);
    try {
      const hits = await searchByImage(file);
      setAssets(hits.map((h) => h.asset));
      setTotal(hits.length);
      notify(hits.length ? `以图搜图：找到 ${hits.length} 个相似素材` : "没有找到相似素材");
    } catch (e) {
      notify(`以图搜图失败：${errMsg(e)}`);
    } finally {
      setGridLoading(false);
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
      const q = query.trim();
      if (q) {
        await runSearch(q, modality, tag);
      } else {
        await runList(modality, tag);
      }
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
      notify(`已删除 #${id}（可在回收站恢复）`);
      await load();
      refreshMeta();
    } catch (e) {
      notify(`删除失败：${errMsg(e)}`);
    }
  };

  const openAssetById = useCallback(
    async (id: number, seek?: number) => {
      try {
        const asset = await fetchAsset(id);
        setSeekTarget(seek ?? null);
        setSelected(asset);
      } catch (e) {
        notify(`加载素材详情失败：${errMsg(e)}`);
      }
    },
    [notify]
  );

  const closeModal = useCallback(() => {
    setSelected(null);
    setSeekTarget(null);
  }, []);

  const handleAssetUpdated = useCallback(
    (a: Asset) => {
      setSelected(a);
      void load();
    },
    [load]
  );

  const handleLogout = () => {
    clearAuth();
    window.location.reload();
  };

  const hasFilter = Boolean(query.trim() || modality || tag || imageSearched);

  return (
    <div className="app workspace">
      <header className="app-header">
        <Link to="/" className="brand-link">
          <span className="brand-mark">M</span>
          <span className="brand-name">Multimodal Asset Agent</span>
        </Link>
        <span className="app-sub">上传什么，就长成什么的素材中心</span>
        <div className="header-right">
          {user ? (
            <>
              <span className="user-chip" title="当前登录用户">
                <UserCircle2 size={14} />
                {user}
              </span>
              <button type="button" className="ghost-chip" onClick={handleLogout}>
                <LogOut size={14} />
                退出
              </button>
            </>
          ) : (
            <Link className="ghost-chip accent" to="/login">
              登录
            </Link>
          )}
          <button type="button" className="ghost-chip" onClick={() => void toggleTrash()}>
            <Trash2 size={14} />
            回收站{trashItems.length > 0 ? ` (${trashItems.length})` : ""}
          </button>
          <a
            className="ghost-chip"
            href="https://github.com/yerouguozi/multimodal-asset-agent"
            target="_blank"
            rel="noreferrer"
          >
            <FolderGit size={14} />
            GitHub
          </a>
          <Link className="ghost-chip" to="/metrics" title="检索实时指标">
            <Activity size={14} />
            指标
          </Link>
          <Link className="ghost-chip" to="/">
            <ArrowLeft size={14} />
            介绍页
          </Link>
        </div>
      </header>

      {notice && (
        <div className="notice" role="status" aria-live="polite">
          <span>{notice}</span>
          <button className="notice-close" aria-label="关闭提示" onClick={() => setNotice("")}>
            <X size={14} />
          </button>
        </div>
      )}

      {showTrash && (
        <section className="panel trash-panel">
          <div className="panel-head">
            <b>回收站</b>
            <button type="button" className="icon-btn sm" onClick={() => void toggleTrash()} aria-label="关闭回收站">
              <X size={14} />
            </button>
          </div>
          {trashBusy && trashItems.length === 0 ? (
            <div className="empty">加载中…</div>
          ) : trashItems.length === 0 ? (
            <div className="empty">回收站是空的</div>
          ) : (
            <div className="trash-list">
              {trashItems.map((a) => (
                <div key={a.id} className="trash-item">
                  <span className="trash-name">
                    #{a.id} {a.name}
                  </span>
                  <span className="trash-meta">
                    {a.modality} · 删除后可恢复
                  </span>
                  <span className="bulk-actions">
                    <button
                      type="button"
                      className="btn soft"
                      onClick={() => void trashAction(a.id, true)}
                      disabled={trashBusy}
                    >
                      恢复
                    </button>
                    <button
                      type="button"
                      className="btn danger"
                      onClick={() => void trashAction(a.id, false)}
                      disabled={trashBusy}
                    >
                      彻底删除
                    </button>
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      <main className="layout">
        <section className="left">
          <UploadPanel onUpload={handleUpload} busy={busy} />
          <SearchBar
            query={query}
            setQuery={setQuery}
            modality={modality}
            onModalityChange={handleModalityChange}
            tag={tag}
            setTag={setTag}
            onSearch={handleSearch}
            onReset={handleReset}
            onImageSearch={handleImageSearch}
          />
          <AssetGrid
            assets={assets}
            total={total}
            loading={gridLoading}
            hasFilter={hasFilter}
            onOpen={setSelected}
            onDelete={handleDelete}
            onReset={handleReset}
          />
        </section>

        <aside className="right">
          <ChatPanel
            onComplete={() => { void load(); refreshMeta(); }}
            onOpenAsset={(id, seek) => void openAssetById(id, seek)}
          />
          <DomainProfileCard profile={profile} usage={usage} onRefresh={refreshMeta} />
        </aside>
      </main>

      {selected && (
        <AssetDetailModal
          asset={selected}
          initialSeek={seekTarget}
          onClose={closeModal}
          onDelete={handleDelete}
          onUpdated={handleAssetUpdated}
        />
      )}
    </div>
  );
}
