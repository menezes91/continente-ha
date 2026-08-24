/* O painel da barra lateral.
 *
 * O `panel_custom` do Home Assistant precisa de um web component — não aceita
 * um URL directamente, como o antigo `panel_iframe` aceitava. Este componente
 * não faz mais nada senão embeber a página que a integração serve.
 */
class ContinentePanel extends HTMLElement {
  connectedCallback() {
    if (this._built) return;
    this._built = true;

    this.style.cssText = 'display:block;height:100%;width:100%';

    const frame = document.createElement('iframe');
    frame.src = '/api/continente/panel/app.html';
    frame.setAttribute('title', 'Continente');
    frame.style.cssText =
      'border:0;width:100%;height:100%;display:block;background:var(--primary-background-color)';
    this.appendChild(frame);
  }
}

customElements.define('continente-panel', ContinentePanel);
