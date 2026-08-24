/* O painel da barra lateral.
 *
 * O `panel_custom` do Home Assistant precisa de um web component — não aceita
 * um URL directamente, como o antigo `panel_iframe` aceitava. Este componente
 * não faz mais nada senão embeber a página que a integração serve.
 *
 * A altura é `100vh` e não `100%`: o elemento onde o Home Assistant nos
 * coloca não tem altura própria, por isso uma percentagem não teria de quê
 * herdar e o iframe encolhia para o tamanho do conteúdo inicial.
 */
class ContinentePanel extends HTMLElement {
  connectedCallback() {
    if (this._built) return;
    this._built = true;

    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100vh;
          width: 100%;
          overflow: hidden;
          background: var(--primary-background-color, #111213);
        }
        iframe {
          display: block;
          border: 0;
          width: 100%;
          height: 100%;
        }
      </style>
      <iframe src="/api/continente/panel/app.html" title="Continente"></iframe>
    `;
  }
}

customElements.define('continente-panel', ContinentePanel);
