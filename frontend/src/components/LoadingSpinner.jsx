import React from 'react';
import './LoadingSpinner.css';
import { useLanguage } from '../contexts/LanguageContext';

const LoadingSpinner = ({ fullPage = true, message, detail }) => {
    const { t } = useLanguage();

    return (
        <div
            className={`loading-container ${fullPage ? 'full-page' : ''}`}
            role="status"
            aria-live="polite"
            aria-busy="true"
            aria-label={message || t('loading')}
        >
            <div className="spinner-wrapper">
                <div className="loading-mark" aria-hidden="true">
                    <span>C</span><span>K</span>
                </div>
                <div className="loading-text">{message || t('loading')}</div>
                {detail && <p className="loading-detail">{detail}</p>}
                <div className="loading-progress" aria-hidden="true"><span /></div>
            </div>
        </div>
    );
};

export default LoadingSpinner;
