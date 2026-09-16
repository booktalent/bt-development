import React, { createContext, useCallback, useContext, useState } from "react";

const ToastCtx = createContext(null);

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);

  const push = useCallback((message, type = "success") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-container" data-testid="toast-container">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.type}`} data-testid={`toast-${t.type}`}>
            <span>{t.type === "success" ? "✓" : t.type === "error" ? "⚠" : "ℹ"}</span>
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
};

export const useToast = () => useContext(ToastCtx);
