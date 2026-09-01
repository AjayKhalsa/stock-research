import React from 'react';
import LegacyResearch from './App';
import CfoWorkspace from './cfo/CfoWorkspace';

export default function RootApp() {
  const enabled = process.env.REACT_APP_CFO_WORKSPACE_V1 !== 'false';
  return enabled ? <CfoWorkspace /> : <LegacyResearch />;
}
