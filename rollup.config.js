import resolve from '@rollup/plugin-node-resolve';
//import eslint from '@rollup/plugin-eslint'; 
import json from '@rollup/plugin-json';
import typescript from '@rollup/plugin-typescript';

export default [
  {
    input: [
      'client/dashboard.ts',
      'client/login.ts',
      'client/task_loader.ts',
      'client/task_consent.ts',
      'client/task_incomplete.ts',
      'client/task_qnaire.ts',
      'client/task_thankyou.ts'
    ],
    output: {
      format: 'es',
      //file: 'expert/static/js/dashboard.js'
      dir: 'expert/static/js',
      chunkFileNames: '[name].js', // don't put hashes in names
      sourcemap: true
    },
    plugins: [
      resolve(), // so Rollup can find external modules
      /*eslint({ 
        exclude: ['./node_modules/**', './src/style/**'], 
        fix: true,
      }),*/
      json(),
      typescript()
    ],
  }
];
