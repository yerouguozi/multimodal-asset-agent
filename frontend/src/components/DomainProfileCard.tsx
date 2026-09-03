import type { ComponentType } from "react";
import {
  Activity,
  Boxes,
  FileText,
  Film,
  Image as ImageIcon,
  Mic,
  RefreshCw,
  Wallet,
} from "lucide-react";
import type { DomainProfile, UsageSummary } from "../types";

interface Props {
  profile: DomainProfile | null;
  usage: UsageSummary | null;
  onRefresh: () => void;
}

const MODALITY_ICON: Record<string, ComponentType<{ size?: number | string; className?: string }>> = {
  image: ImageIcon,
  video: Film,
  audio: Mic,
  document: FileText,
};

const MODALITY_NAME: Record<string, string> = {
  image: "图片",
  video: "视频",
  audio: "音频",
  document: "文档",
};

function ProfileSkeleton() {
  return (
    <div aria-hidden="true">
      <div className="skeleton-block line w90" />
      <div className="skeleton-block line w100" />
      <div className="skeleton-block line w80" />
      <div className="skeleton-block line w90" />
    </div>
  );
}

export default function DomainProfileCard({ profile, usage, onRefresh }: Props) {
  return (
    <section className="panel profile-panel" aria-label="素材库画像">
      <div className="panel-head">
        <b>素材库画像</b>
        <button
          type="button"
          className="icon-btn"
          onClick={onRefresh}
          aria-label="刷新画像与用量"
          title="刷新"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {profile ? (
        <>
          <p className="profile-summary">{profile.summary}</p>

          {profile.labels.length > 0 && (
            <div className="tags profile-labels">
              {profile.labels.map((l, i) => (
                <span key={i} className="tag label">
                  {l}
                </span>
              ))}
            </div>
          )}

          <div className="profile-bars" role="list" aria-label="素材类型分布">
            {Object.entries(profile.by_modality).map(([m, c]) => {
              const Icon = MODALITY_ICON[m] ?? FileText;
              const pct = (c / Math.max(1, profile.total)) * 100;
              return (
                <div key={m} className="bar-row" role="listitem">
                  <span className="bar-label">
                    <span className={`bar-icon ${m}`}>
                      <Icon size={12} aria-hidden="true" />
                    </span>
                    <span>{MODALITY_NAME[m] ?? m}</span>
                    <span className="bar-count">{c}</span>
                    <span className="bar-pct">{pct.toFixed(0)}%</span>
                  </span>
                  <div className="bar">
                    <div className="bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>

          <div className="profile-stats">
            <div className="mini-stat">
              <Activity size={14} aria-hidden="true" />
              <span>
                <b>{usage?.total_calls ?? "—"}</b>
                <i>模型调用</i>
              </span>
            </div>
            <div className="mini-stat">
              <Wallet size={14} aria-hidden="true" />
              <span>
                <b>${usage ? usage.total_cost.toFixed(4) : "—"}</b>
                <i>估算成本</i>
              </span>
            </div>
            <div className="mini-stat">
              <Boxes size={14} aria-hidden="true" />
              <span>
                <b>{usage && usage.by_model ? Object.keys(usage.by_model).length : "—"}</b>
                <i>接入模型</i>
              </span>
            </div>
          </div>

          <div className="weights">
            自适应检索权重
            <code>{JSON.stringify(profile.adaptive_weights)}</code>
          </div>
        </>
      ) : (
        <ProfileSkeleton />
      )}
    </section>
  );
}
