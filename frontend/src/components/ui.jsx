import { AlertCircle, Loader2 } from 'lucide-react';

export function Button({ children, icon: Icon, variant = 'primary', loading = false, loadingLabel, disabled, className = '', ...props }) {
  const LeadingIcon = loading ? Loader2 : Icon;
  return (
    <button className={`button ${variant} ${className}`.trim()} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
      {LeadingIcon ? <LeadingIcon className={loading ? 'spin' : ''} size={16} /> : null}
      <span>{loading ? loadingLabel || children : children}</span>
    </button>
  );
}

export function IconButton({ label, icon: Icon, className = '', ...props }) {
  return (
    <button className={`icon-button ${className}`.trim()} title={label} aria-label={label} {...props}>
      <Icon size={16} />
    </button>
  );
}

export function Field({ label, children, help }) {
  return (
    <label className="field">
      <span>
        {label}
        {help ? <small>{help}</small> : null}
      </span>
      {children}
    </label>
  );
}

export function Panel({ title, actions, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) ? (
        <div className="panel-title-row">
          {title ? <h2>{title}</h2> : <span />}
          {actions ? <div className="button-row">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function HelpDot({ text }) {
  return (
    <span className="help-dot" title={text} aria-label={text}>
      ?
    </span>
  );
}

export function StatusPill({ status }) {
  const value = status || 'not_indexed';
  const labels = {
    ready: '已就绪',
    stale: '待更新',
    not_indexed: '未索引',
    processing: '处理中',
    indexing: '索引中',
    pending: '等待中',
    running: '运行中',
    failed: '失败',
    completed: '已完成',
  };
  return <span className={`status-pill status-${value}`}>{labels[value] || value}</span>;
}

export function EmptyState({ title, body }) {
  return (
    <div className="empty-state">
      <AlertCircle size={18} />
      <strong>{title}</strong>
      {body ? <span>{body}</span> : null}
    </div>
  );
}
