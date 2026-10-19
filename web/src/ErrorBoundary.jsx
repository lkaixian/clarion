import { Component } from "react";
import { tr } from "./lib/i18n";

export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Unhandled UI error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
          <h1>{tr("Something went wrong")}</h1>
          <p>{tr("Reload the page. If this keeps happening, contact IT support.")}</p>
        </div>
      );
    }
    return this.props.children;
  }
}
