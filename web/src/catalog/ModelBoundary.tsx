import { Component, type ReactNode } from "react";

// 3D-модель не загрузилась (файл повреждён, сжат незнакомым способом, декодер не пришёл) — на
// её месте запасной вид. Без этого ошибка загрузки внутри сцены роняет всю страницу (DWG3D-15).
// Новая модель — новый key у границы, иначе она так и показывает запасной вид.
interface Props {
  url: string;
  fallback: ReactNode;
  onError?: () => void;
  children: ReactNode;
}

export class ModelBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error(`3D-модель ${this.props.url} не загрузилась`, error);
    this.props.onError?.();
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
