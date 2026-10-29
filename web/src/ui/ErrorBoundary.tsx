import { Component, type ReactNode } from "react";
import { useLocation } from "react-router";
import { Button } from "./button";

// Граница ошибок отрисовки (R-032): исключение в разделе не снимает всё приложение — на его
// месте сообщение, а меню и строка сверху работают. Сменился resetKey (перешли в другой
// раздел) — граница снова показывает содержимое.
interface Props {
  children: ReactNode;
  fallback?: (retry: () => void) => ReactNode;
  resetKey?: unknown;
}

interface State {
  failed: boolean;
  key: unknown;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, key: undefined };

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey === state.key ? null : { failed: false, key: props.resetKey };
  }

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Сбой отрисовки", error);
  }

  retry = () => this.setState({ failed: false });

  render() {
    if (!this.state.failed) return this.props.children;
    return this.props.fallback ? this.props.fallback(this.retry) : <Failed />;
  }
}

function Failed() {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <div className="text-base font-medium">Раздел не открылся</div>
      <div className="max-w-md text-sm text-ink-2">
        В интерфейсе произошла ошибка. Перезагрузите страницу; если ошибка повторяется — сообщите тому, кто обслуживает систему.
      </div>
      <Button onClick={() => window.location.reload()}>Перезагрузить</Button>
    </div>
  );
}

// Граница раздела в каркасе: перешли в другой раздел — пробует показать его
export function SectionBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return <ErrorBoundary resetKey={pathname}>{children}</ErrorBoundary>;
}
