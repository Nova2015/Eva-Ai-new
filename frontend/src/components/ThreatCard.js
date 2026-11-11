// Frontend/src/components/ThreatCard.js

import React from "react";

const ThreatCard = ({ threat }) => {

    return (

        <div
            style={{
                background: "#1e1e1e",
                color: "#fff",
                padding: "20px",
                borderRadius: "10px",
                marginBottom: "15px",
                borderLeft: "5px solid red"
            }}
        >

            <h3>{threat.type}</h3>

            <p>
                Severity: <strong>{threat.severity}</strong>
            </p>

            <p>
                Message: {threat.message}
            </p>

            <p>
                Time: {threat.timestamp}
            </p>

        </div>
    );
};

export default ThreatCard;