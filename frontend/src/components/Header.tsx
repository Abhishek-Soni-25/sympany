/** Sympany logo — image only (frontend/public/sympany-logo.svg). */
function BrandLogo() {
  return (
    <div className="logo">
      <img src="/sympany-logo.svg" alt="Sympany" className="logo-img" />
    </div>
  );
}

export function Header({
  running,
  onScan,
}: {
  running: boolean;
  onScan: () => void;
}) {
  return (
    <header className="app-header">
      <BrandLogo />
      <div className="header-actions">
        <button className="btn" onClick={onScan} disabled={running}>
          {running ? (
            <>
              <span className="spinner" /> Scanning…
            </>
          ) : (
            <>▶ Run Scan</>
          )}
        </button>
      </div>
    </header>
  );
}
