import type { ButtonHTMLAttributes } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** ボタンに表示する文字列 */
  label: string;
  /** 見た目の種類 */
  variant?: ButtonVariant;
}

export function Button({ label, variant = 'primary', type = 'button', className, ...rest }: ButtonProps) {
  const classes = ['btn', `btn--${variant}`, className].filter(Boolean).join(' ');
  return (
    <button type={type} className={classes} {...rest}>
      {label}
    </button>
  );
}
