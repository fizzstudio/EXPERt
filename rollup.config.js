import resolve from '@rollup/plugin-node-resolve';
import eslint from '@rollup/plugin-eslint'; 

export default [
  {
    input: [
      'build/dashboard.js',
      'build/task_loader.js',
      'build/task_consent.js',
      'build/task_incomplete.js',
      'build/task_qnaire.js',
      'build/task_thankyou.js'
    ],
    output: {
      format: 'es',
      //file: 'expert/static/js/dashboard.js'
      dir: 'expert/static/js'
    },
    plugins: [
      resolve(), // so Rollup can find external modules
      eslint({ 
        exclude: ['./node_modules/**', './src/style/**'], 
        fix: true,
      }),
    ],
  }
];
