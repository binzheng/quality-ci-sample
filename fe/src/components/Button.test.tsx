import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Button } from './Button';

describe('Button', () => {
  it('renders the label with the primary variant by default', () => {
    render(<Button label="保存" />);
    const button = screen.getByRole('button', { name: '保存' });
    expect(button).toHaveClass('btn', 'btn--primary');
    expect(button).toHaveAttribute('type', 'button');
  });

  it('applies the given variant and extra class', () => {
    render(<Button label="削除" variant="danger" className="extra" />);
    expect(screen.getByRole('button')).toHaveClass('btn--danger', 'extra');
  });

  it('calls onClick when clicked', () => {
    const onClick = vi.fn();
    render(<Button label="押す" onClick={onClick} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('does not call onClick when disabled', () => {
    const onClick = vi.fn();
    render(<Button label="押す" onClick={onClick} disabled />);
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).not.toHaveBeenCalled();
  });
});
