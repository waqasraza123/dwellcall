"use client";

import { useEffect, useId, useRef } from "react";


export type ConfirmAction = {
  title: string;
  description: string;
  label: string;
  path: string;
  fields?: Record<string, unknown>;
};

export function ConfirmActionDialog({
  action,
  busy,
  onClose,
  onConfirm,
}: {
  action: ConfirmAction;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const title = useId();
  const description = useId();

  useEffect(() => {
    const element = dialog.current;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    element?.showModal();
    cancel.current?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      element?.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected)
        previousFocus.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className="confirmation"
      aria-labelledby={title}
      aria-describedby={description}
      aria-busy={busy}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <h3 id={title}>{action.title}</h3>
      <p id={description}>{action.description}</p>
      <div className="actions">
        <button
          ref={cancel}
          type="button"
          className="secondary"
          disabled={busy}
          onClick={onClose}
        >
          Cancel
        </button>
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={onConfirm}
        >
          {busy ? "Updating…" : action.label}
        </button>
      </div>
    </dialog>
  );
}

