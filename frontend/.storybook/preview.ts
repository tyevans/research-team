import type { Preview } from '@storybook/react-vite'

// The whole stylesheet, exactly as `main.tsx` loads it. A workbench styled by a
// subset of the application's CSS is a workbench that lies: the console's
// appearance depends on `tokens.css` for its palette and on `structure.css`
// last of all to correct the files above it, so anything less than the real
// import chain renders components that look right nowhere else.
import '../src/styles/index.css'

const preview: Preview = {
  parameters: {
    // Dark, because the console is. Storybook's default is white and every
    // component here is drawn for `--bg: #0b0d10`; on white they are illegible
    // and, worse, they are illegible in a way that looks like a component bug.
    backgrounds: {
      options: { console: { name: 'console', value: '#0b0d10' } },
    },
  },
  initialGlobals: { backgrounds: { value: 'console' } },
}

export default preview
