import { fireEvent, render, screen } from '@testing-library/react';
import Screener from './Screener';
import { resolveSymbols } from '../api';

jest.mock('../api', () => ({
  API_BASE: 'http://localhost:8000',
  resolveSymbols: jest.fn(),
  saveScreen: jest.fn(),
}));

class MockEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.close = jest.fn();
    MockEventSource.instances.push(this);
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  global.EventSource = MockEventSource;
  resolveSymbols.mockReset();
});

afterEach(() => {
  delete global.EventSource;
});

test('starts uppercase ticker lists without a redundant resolver request', () => {
  render(<Screener />);

  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: 'RELIANCE, TCS, INFY' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Analyze 3 stocks/i }));

  expect(resolveSymbols).not.toHaveBeenCalled();
  expect(MockEventSource.instances).toHaveLength(1);
  expect(MockEventSource.instances[0].url).toContain('symbols=RELIANCE%2CTCS%2CINFY');
  expect(screen.getByRole('status')).toHaveTextContent('Starting analysis');
});

test('lets the user cancel an in-progress stream', () => {
  render(<Screener />);
  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: 'RELIANCE, TCS' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Analyze 2 stocks/i }));
  fireEvent.click(screen.getByRole('button', { name: /Cancel/i }));

  expect(MockEventSource.instances[0].close).toHaveBeenCalled();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});
