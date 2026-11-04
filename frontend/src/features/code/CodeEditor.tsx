import { indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { useEffect, useLayoutEffect, useRef } from "react";

/** CodeMirror 6 with Python highlighting, line numbers and auto-indent. Tab indents; Esc then
 * Tab leaves the editor (CodeMirror's escape hatch). Ctrl/Cmd+Enter calls `onRun`.
 *
 * Uncontrolled after mount: `value` is the starting text (remount with a `key` to reset). */
export function CodeEditor({
  value,
  onChange,
  onRun,
  readOnly = false,
  labelledBy,
  describedBy,
}: {
  value: string;
  onChange: (value: string) => void;
  onRun?: () => void;
  readOnly?: boolean;
  labelledBy?: string;
  describedBy?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const callbacks = useRef({ onChange, onRun });
  useLayoutEffect(() => {
    callbacks.current = { onChange, onRun };
  });

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          keymap.of([
            {
              key: "Mod-Enter",
              preventDefault: true,
              run: () => {
                callbacks.current.onRun?.();
                return true;
              },
            },
            indentWithTab,
          ]),
          basicSetup,
          python(),
          EditorState.readOnly.of(readOnly),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) callbacks.current.onChange(update.state.doc.toString());
          }),
          EditorView.contentAttributes.of({
            "aria-label": "Code editor",
            ...(labelledBy ? { "aria-labelledby": labelledBy } : {}),
            ...(describedBy ? { "aria-describedby": describedBy } : {}),
          }),
          EditorView.theme({
            "&": { fontSize: "14px", height: "100%" },
            ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // Mount once per key: later `value` changes come from the editor itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly]);

  return (
    <div
      ref={host}
      data-testid="code-editor"
      className="h-[24rem] min-h-40 resize-y overflow-auto rounded-md border bg-background text-left"
    />
  );
}
