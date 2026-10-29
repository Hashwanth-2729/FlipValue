import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { MetaProvider } from "./meta";
import { AdminPage } from "./pages/AdminPage";
import { ComparePage } from "./pages/ComparePage";
import { DevelopersPage } from "./pages/DevelopersPage";
import { DevicesPage } from "./pages/DevicesPage";
import { HomePage } from "./pages/HomePage";
import {
  AboutPage,
  ApiDocsPage,
  ContactPage,
  DataSourcesPage,
  MethodologyPage,
  NotFoundPage,
  PrivacyPage,
  TermsPage,
} from "./pages/InfoPages";
import { PricesPage } from "./pages/PricesPage";
import { SavedListPage, SavedViewPage } from "./pages/SavedPages";
import { TrendsPage } from "./pages/TrendsPage";
import { ValuePage } from "./pages/ValuePage";
import { WatchlistPage } from "./pages/WatchlistPage";

export function App() {
  return (
    <MetaProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="value" element={<ValuePage />} />
          <Route path="devices" element={<DevicesPage />} />
          <Route path="compare" element={<ComparePage />} />
          <Route path="trends" element={<TrendsPage />} />
          <Route path="prices" element={<PricesPage />} />
          <Route path="developers" element={<DevelopersPage />} />
          <Route path="watchlist" element={<WatchlistPage />} />
          <Route path="saved" element={<SavedListPage />} />
          <Route path="v/:id" element={<SavedViewPage />} />
          <Route path="methodology" element={<MethodologyPage />} />
          <Route path="data-sources" element={<DataSourcesPage />} />
          <Route path="privacy" element={<PrivacyPage />} />
          <Route path="terms" element={<TermsPage />} />
          <Route path="about" element={<AboutPage />} />
          <Route path="api" element={<ApiDocsPage />} />
          <Route path="contact" element={<ContactPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </MetaProvider>
  );
}
