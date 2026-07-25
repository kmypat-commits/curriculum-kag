import React from 'react';
import './LoadingSpinner.css';
import { useLanguage } from '../contexts/LanguageContext';

const LoadingSpinner = ({ fullPage = true }) => {
    const { t } = useLanguage();

    return (
        <div className={`loading-container ${fullPage ? 'full-page' : ''}`}>
            <div className="spinner-wrapper">
                <div className="loading-mark" aria-hidden="true">
                    <span>C</span><span>K</span>
                </div>
                <div className="loading-text">{t('loading')}</div>
                <div className="loading-progress" aria-hidden="true"><span /></div>
            </div>
        </div>
    );
};

export default LoadingSpinner;
